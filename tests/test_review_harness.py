from __future__ import annotations

import tempfile
import unittest
import unittest.mock
import json
from copy import deepcopy
from pathlib import Path

from core.review_harness.checkpoints import CheckpointError, abandon, authorize, create, inspect, record_outcome, resume
from core.review_harness import contracts
from core.review_harness.contracts import (
    ContractError,
    binding_digest,
    match_command_binding,
    migrate_sources_v1,
    validate_sources,
)
from core.review_harness.gate import evaluate_action
from core.review_harness.schemas import sources_schema


def sources() -> dict:
    return {
        "version": 2,
        "scm": {
            "capabilities": {
                "post_inline_comment": {
                    "kind": "mcp_tool", "server": "github", "tool": "post_comment",
                    "access": "write", "effect": "scm.comment.create",
                },
                "get_pull_request": {
                    "kind": "command", "program": "gh", "args": ["pr", "view", "{pull_request_id}"],
                    "access": "read", "effect": "scm.pull_request.read",
                },
            },
            "unsupported": [],
        },
        "tracker": {"capabilities": {}, "unsupported": ["fetch_work_item"]},
    }


class SourcesContractTest(unittest.TestCase):
    def test_checked_in_schema_snapshot_matches_the_contract_registry(self):
        path = Path(__file__).resolve().parents[1] / "core" / "review_harness" / "schema" / "sources-v2.schema.json"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), sources_schema())

    def test_validates_typed_bindings_and_returns_a_stable_digest(self):
        first = validate_sources(sources())
        self.assertEqual(binding_digest(first), binding_digest(sources()))

    def test_rejects_unknown_binding_and_wrong_effect(self):
        value = sources()
        value["scm"]["capabilities"]["post_inline_comment"]["effect"] = "scm.pull_request.read"
        with self.assertRaises(ContractError):
            validate_sources(value)
        value = sources()
        value["scm"]["capabilities"]["post_inline_comment"]["extra"] = True
        with self.assertRaises(ContractError):
            validate_sources(value)

    def test_migrates_exact_mcp_references_but_refuses_ambiguous_shell(self):
        v1 = {
            "version": 1,
            "scm": {"capabilities": {"post_inline_comment": "mcp__github__post_comment"}, "unsupported": []},
            "tracker": {"capabilities": {}, "unsupported": []},
        }
        migrated, diagnostics = migrate_sources_v1(v1)
        self.assertEqual(diagnostics, [])
        self.assertEqual(migrated["version"], 2)
        v1["scm"]["capabilities"]["post_inline_comment"] = "gh pr comment 1 --body x | tee log"
        migrated, diagnostics = migrate_sources_v1(v1)
        self.assertIsNone(migrated)
        self.assertTrue(diagnostics)


    def test_a_non_iterable_capability_map_raises_contract_error(self):
        for malformed in (5, None, True, 1.5):
            with self.subTest(capabilities=malformed):
                value = sources()
                value["scm"]["capabilities"] = malformed
                with self.assertRaises(ContractError):
                    validate_sources(value)

    def test_a_malformed_unsupported_list_raises_contract_error(self):
        for malformed in ("post_inline_comment", 7, {"post_inline_comment": True}, ["post_inline_comment", 3]):
            with self.subTest(unsupported=malformed):
                value = sources()
                value["scm"]["unsupported"] = malformed
                with self.assertRaises(ContractError):
                    validate_sources(value)

    def test_a_capability_declared_in_the_wrong_area_is_rejected(self):
        value = sources()
        value["tracker"]["capabilities"]["post_inline_comment"] = {
            "kind": "mcp_tool", "server": "github", "tool": "post_comment",
            "access": "write", "effect": "scm.comment.create",
        }
        with self.assertRaises(ContractError):
            validate_sources(value)

        value = sources()
        value["scm"]["capabilities"]["fetch_work_item"] = {
            "kind": "mcp_tool", "server": "tracker", "tool": "get_item",
            "access": "read", "effect": "tracker.work_item.read",
        }
        with self.assertRaises(ContractError):
            validate_sources(value)

    def test_a_write_capability_cannot_be_bound_to_a_path(self):
        value = sources()
        value["scm"]["capabilities"]["post_inline_comment"] = {
            "kind": "path", "path": "docs/comment.md",
            "access": "write", "effect": "scm.comment.create",
        }
        with self.assertRaises(ContractError):
            validate_sources(value)

    def test_a_binding_cannot_declare_the_wrong_access_for_its_capability(self):
        value = sources()
        value["scm"]["capabilities"]["post_inline_comment"]["access"] = "read"
        with self.assertRaises(ContractError):
            validate_sources(value)

        value = sources()
        value["scm"]["capabilities"]["get_pull_request"]["access"] = "write"
        with self.assertRaises(ContractError):
            validate_sources(value)

    def test_migration_refuses_every_shell_composition_shape(self):
        composed = (
            "gh pr comment 1 --body x; echo done",
            "gh pr comment 1 --body x | tee log",
            "gh pr comment 1 --body x && rm -rf /tmp/x",
            "gh pr comment 1 --body x || true",
            "gh pr comment 1 --body x > /tmp/out",
            "gh pr comment 1 --body x >> /tmp/out",
            "gh pr comment 1 --body x < /tmp/in",
            "gh pr comment 1 --body `whoami`",
            "gh pr comment 1 --body $(whoami)",
            "gh pr comment 1 --body ${HOME}",
            "gh pr comment 1 --body (x)",
            "gh pr comment 1 --body x\necho done",
            "gh pr comment 1 --body x &",
        )
        for raw in composed:
            with self.subTest(raw=raw):
                v1 = {
                    "version": 1,
                    "scm": {"capabilities": {"post_inline_comment": raw}, "unsupported": []},
                    "tracker": {"capabilities": {}, "unsupported": []},
                }
                migrated, diagnostics = migrate_sources_v1(v1)
                self.assertIsNone(migrated, f"{raw!r} was migrated into a typed binding")
                self.assertTrue(diagnostics)

    def test_an_ambiguous_migration_reports_rerun_review_setup_and_changes_nothing(self):
        v1 = {
            "version": 1,
            "scm": {
                "capabilities": {
                    "post_inline_comment": "gh pr comment 1 --body x && echo done",
                    "get_pull_request": "mcp__github__get_pull_request",
                },
                "unsupported": [],
            },
            "tracker": {"capabilities": {}, "unsupported": []},
        }
        before = deepcopy(v1)
        migrated, diagnostics = migrate_sources_v1(v1)
        self.assertIsNone(migrated)
        self.assertEqual(v1, before, "an ambiguous document must not be partially migrated")
        self.assertTrue(any("rerun review-setup" in item for item in diagnostics))


class PrevalidatedDigestTest(unittest.TestCase):
    def test_a_prevalidated_document_is_not_validated_again(self):
        normalized = validate_sources(sources())
        with unittest.mock.patch.object(
            contracts, "validate_sources", wraps=contracts.validate_sources
        ) as spy:
            digest = binding_digest(normalized, prevalidated=True)
        self.assertEqual(spy.call_count, 0)
        self.assertEqual(digest, binding_digest(sources()))

    def test_an_unvalidated_document_is_still_validated_once(self):
        with unittest.mock.patch.object(
            contracts, "validate_sources", wraps=contracts.validate_sources
        ) as spy:
            binding_digest(sources())
        self.assertEqual(spy.call_count, 1)


class CommandBindingMatchTest(unittest.TestCase):
    def binding(self, args: list[str]) -> dict:
        return {
            "kind": "command", "program": "gh", "args": args,
            "access": "write", "effect": "scm.comment.create",
        }

    def test_a_matching_argv_yields_the_captured_placeholders(self):
        binding = self.binding(["pr", "comment", "{pull_request_id}", "--body", "{body}"])
        self.assertEqual(
            match_command_binding(binding, ["gh", "pr", "comment", "42", "--body", "text [mcrt:f1]"]),
            {"pull_request_id": "42", "body": "text [mcrt:f1]"},
        )

    def test_a_placeholder_embedded_in_a_flag_is_captured(self):
        binding = self.binding(["pr", "comment", "{pull_request_id}", "--body-file={body_file}"])
        self.assertEqual(
            match_command_binding(binding, ["gh", "pr", "comment", "7", "--body-file=/tmp/body.md"]),
            {"pull_request_id": "7", "body_file": "/tmp/body.md"},
        )

    def test_a_template_without_placeholders_matches_and_captures_nothing(self):
        binding = self.binding(["pr", "list"])
        self.assertEqual(match_command_binding(binding, ["gh", "pr", "list"]), {})

    def test_a_literal_mismatch_does_not_match(self):
        binding = self.binding(["pr", "comment", "{pull_request_id}"])
        self.assertIsNone(match_command_binding(binding, ["gh", "issue", "comment", "42"]))

    def test_a_different_argument_count_does_not_match(self):
        binding = self.binding(["pr", "comment", "{pull_request_id}"])
        self.assertIsNone(match_command_binding(binding, ["gh", "pr", "comment", "42", "--body", "x"]))
        self.assertIsNone(match_command_binding(binding, ["gh", "pr", "comment"]))

    def test_another_program_does_not_match(self):
        binding = self.binding(["pr", "comment", "{pull_request_id}"])
        self.assertIsNone(match_command_binding(binding, ["glab", "pr", "comment", "42"]))

    def test_an_absolute_program_path_still_matches(self):
        binding = self.binding(["pr", "comment", "{pull_request_id}"])
        self.assertEqual(
            match_command_binding(binding, ["/usr/local/bin/gh", "pr", "comment", "42"]),
            {"pull_request_id": "42"},
        )

    def test_a_repeated_placeholder_must_capture_the_same_value(self):
        binding = self.binding(["pr", "comment", "{pull_request_id}", "--repo-pr", "{pull_request_id}"])
        self.assertEqual(
            match_command_binding(binding, ["gh", "pr", "comment", "42", "--repo-pr", "42"]),
            {"pull_request_id": "42"},
        )
        self.assertIsNone(
            match_command_binding(binding, ["gh", "pr", "comment", "42", "--repo-pr", "43"])
        )

    def test_a_placeholder_cannot_absorb_a_literal_neighbour(self):
        binding = self.binding(["pr", "comment", "{pull_request_id}", "--body", "{body}"])
        self.assertIsNone(match_command_binding(binding, ["gh", "pr", "comment", "42", "--bodyx", "t"]))

    def test_a_non_command_binding_never_matches(self):
        mcp = {"kind": "mcp_tool", "server": "github", "tool": "post_comment", "access": "write", "effect": "scm.comment.create"}
        self.assertIsNone(match_command_binding(mcp, ["gh", "pr", "comment", "42"]))
        self.assertIsNone(match_command_binding(None, ["gh"]))
        self.assertIsNone(match_command_binding(self.binding(["pr"]), []))


class GateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.digest = binding_digest(sources())
        self.identity = {
            "workspace": str(self.workspace), "repository": "Monolith-INC/mcrt",
            "pull_request_id": "42", "binding_digest": self.digest,
        }

    def tearDown(self):
        self.temp.cleanup()

    def event(self, **overrides):
        return {
            "mcrt": True, "role": "poster", "finding_ids": ["finding-1"],
            **self.identity, **overrides,
        }

    def test_unrelated_actions_are_inert(self):
        self.assertTrue(evaluate_action(None, {"mcrt": False}).allowed)

    def test_authorizes_once_then_denies_a_repeat(self):
        path = create(self.workspace, self.identity, ["finding-1"])
        self.assertTrue(authorize(path, self.event()).allowed)
        self.assertFalse(authorize(path, self.event()).allowed)

    def test_denies_identity_and_approval_mismatches(self):
        path = create(self.workspace, self.identity, ["finding-1"])
        self.assertFalse(authorize(path, self.event(pull_request_id="43")).allowed)
        self.assertFalse(authorize(path, self.event(finding_ids=["finding-2"])).allowed)

    def test_resume_abandon_and_outcome_are_explicit(self):
        path = create(self.workspace, self.identity)
        checkpoint = inspect(path)
        checkpoint["status"] = "paused"
        path.write_text(__import__("json").dumps(checkpoint), encoding="utf-8")
        self.assertEqual(resume(path)["status"], "running")
        self.assertEqual(abandon(path, "operator stopped run")["status"], "abandoned")
        with self.assertRaises(CheckpointError):
            resume(path)
        path = create(self.workspace, self.identity, ["finding-1"])
        authorize(path, self.event())
        self.assertEqual(record_outcome(path, "tool-1", True)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
