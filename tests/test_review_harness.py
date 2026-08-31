from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock
import json
from copy import deepcopy
from pathlib import Path

from core.review_harness.checkpoints import (
    CheckpointError,
    abandon,
    authorize,
    create,
    directory,
    find_active_checkpoint,
    inspect,
    record_outcome,
    resume,
)
from core.review_harness import contracts
from core.review_harness.contracts import (
    ContractError,
    binding_digest,
    match_command_binding,
    migrate_sources_v1,
    validate_sources,
)
from core.review_harness.gate import evaluate_action
from core.review_harness.contracts import (
    READ_CAPABILITIES,
    SCM_CAPABILITIES,
    TRACKER_CAPABILITIES,
    WRITE_CAPABILITIES,
    EFFECTS,
)
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


class SchemaEvidenceTest(unittest.TestCase):
    def capability_branches(self, capability: str) -> list[dict]:
        definition = sources_schema()["$defs"]["source"]["properties"]["capabilities"]["properties"][capability]
        return definition["oneOf"]

    def area_enum(self, area: str) -> list[str]:
        wrapper = sources_schema()["$defs"][area]
        for member in wrapper["allOf"]:
            names = member.get("properties", {}).get("capabilities", {}).get("propertyNames")
            if names:
                return names["enum"]
        self.fail(f"{area} does not restrict which capabilities it owns")

    def test_every_capability_has_its_own_branch(self):
        properties = sources_schema()["$defs"]["source"]["properties"]["capabilities"]
        self.assertEqual(sorted(properties["properties"]), sorted(WRITE_CAPABILITIES | READ_CAPABILITIES))
        self.assertFalse(properties["additionalProperties"])

    def test_a_capability_fixes_its_access_and_effect(self):
        for capability in sorted(WRITE_CAPABILITIES | READ_CAPABILITIES):
            expected_access = "write" if capability in WRITE_CAPABILITIES else "read"
            with self.subTest(capability=capability):
                for branch in self.capability_branches(capability):
                    self.assertEqual(branch["properties"]["access"], {"const": expected_access})
                    self.assertEqual(branch["properties"]["effect"], {"const": EFFECTS[capability]})

    def test_a_write_capability_has_no_path_alternative(self):
        for capability in sorted(WRITE_CAPABILITIES):
            with self.subTest(capability=capability):
                kinds = {branch["properties"]["kind"]["const"] for branch in self.capability_branches(capability)}
                self.assertEqual(kinds, {"mcp_tool", "command"})

    def test_a_read_capability_keeps_the_path_alternative(self):
        kinds = {branch["properties"]["kind"]["const"] for branch in self.capability_branches("get_pull_request")}
        self.assertEqual(kinds, {"mcp_tool", "command", "path"})

    def test_each_area_declares_only_the_capabilities_it_owns(self):
        self.assertEqual(self.area_enum("scm"), sorted(SCM_CAPABILITIES))
        self.assertEqual(self.area_enum("tracker"), sorted(TRACKER_CAPABILITIES))

    def test_the_scm_section_still_describes_its_repository_identity(self):
        wrapper = sources_schema()["$defs"]["scm"]
        declared = {}
        for member in wrapper["allOf"]:
            declared.update(member.get("properties", {}))
        self.assertIn("owner", declared)
        self.assertIn("repo", declared)


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


class ActiveCheckpointTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {
            "workspace": str(self.root), "repository": "acme/widgets",
            "pull_request_id": "42", "binding_digest": "digest",
        }

    def test_no_checkpoint_directory_has_no_active_checkpoint(self):
        self.assertIsNone(find_active_checkpoint(self.root))

    def test_the_active_checkpoint_wins_over_a_lexicographically_later_terminal_one(self):
        path = create(self.root, self.identity, ["f1"])
        live = json.loads(path.read_text(encoding="utf-8"))
        folder = directory(self.root)
        low = folder / "checkpoint-0000000000000000.json"
        path.rename(low)
        (folder / "checkpoint-ffffffffffffffff.json").write_text(
            json.dumps(dict(live, status="abandoned")), encoding="utf-8"
        )
        self.assertEqual(find_active_checkpoint(self.root), low)

    def test_two_active_checkpoints_are_ambiguous(self):
        path = create(self.root, self.identity, ["f1"])
        live = json.loads(path.read_text(encoding="utf-8"))
        (directory(self.root) / "checkpoint-ffffffffffffffff.json").write_text(
            json.dumps(live), encoding="utf-8"
        )
        with self.assertRaises(CheckpointError):
            find_active_checkpoint(self.root)

    def test_a_malformed_checkpoint_is_not_silently_ignored(self):
        create(self.root, self.identity, ["f1"])
        (directory(self.root) / "checkpoint-ffffffffffffffff.json").write_text("{", encoding="utf-8")
        with self.assertRaises(CheckpointError):
            find_active_checkpoint(self.root)


class CheckpointLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {
            "workspace": str(self.root), "repository": "acme/widgets",
            "pull_request_id": "42", "binding_digest": "digest",
        }

    def event(self, tool_use_id: str, *finding_ids: str) -> dict:
        return dict(self.identity, mcrt=True, role="poster", finding_ids=list(finding_ids), tool_use_id=tool_use_id)

    def test_an_authorization_keeps_the_checkpoint_approved(self):
        path = create(self.root, self.identity, ["f1", "f2"])
        self.assertTrue(authorize(path, self.event("call-1", "f1")).allowed)
        checkpoint = inspect(path)
        self.assertEqual(checkpoint["status"], "approved")
        self.assertEqual(checkpoint["attempted_finding_ids"], ["f1"])
        self.assertIn("call-1", checkpoint["pending_posts"])

    def test_every_approved_finding_can_be_authorized_in_turn(self):
        path = create(self.root, self.identity, ["f1", "f2"])
        self.assertTrue(authorize(path, self.event("call-1", "f1")).allowed)
        record_outcome(path, "call-1", True)
        second = authorize(path, self.event("call-2", "f2"))
        self.assertTrue(second.allowed, second.reason)

    def test_an_authorization_requires_a_tool_use_id(self):
        path = create(self.root, self.identity, ["f1"])
        event = self.event("", "f1")
        with self.assertRaises(CheckpointError):
            authorize(path, event)

    def test_an_outcome_must_match_a_pending_authorization(self):
        path = create(self.root, self.identity, ["f1"])
        authorize(path, self.event("call-1", "f1"))
        with self.assertRaises(CheckpointError):
            record_outcome(path, "some-other-call", True)
        self.assertEqual(inspect(path)["status"], "approved")

    def test_the_run_completes_only_after_every_approved_finding_succeeded(self):
        path = create(self.root, self.identity, ["f1", "f2"])
        authorize(path, self.event("call-1", "f1"))
        record_outcome(path, "call-1", True)
        self.assertEqual(inspect(path)["status"], "approved")
        authorize(path, self.event("call-2", "f2"))
        record_outcome(path, "call-2", True)
        self.assertEqual(inspect(path)["status"], "completed")

    def test_one_authorization_covering_every_finding_completes_the_run(self):
        path = create(self.root, self.identity, ["f1", "f2"])
        authorize(path, self.event("call-1", "f1", "f2"))
        record_outcome(path, "call-1", True)
        self.assertEqual(inspect(path)["status"], "completed")

    def test_a_provider_failure_fails_the_run_without_reopening_attempts(self):
        path = create(self.root, self.identity, ["f1", "f2"])
        authorize(path, self.event("call-1", "f1"))
        checkpoint = record_outcome(path, "call-1", False, "provider rejected the comment")
        self.assertEqual(checkpoint["status"], "failed")
        self.assertEqual(checkpoint["attempted_finding_ids"], ["f1"])

    def test_a_terminal_checkpoint_refuses_every_outcome(self):
        for terminate in ("completed", "failed", "abandoned"):
            with self.subTest(terminal=terminate):
                temp = tempfile.TemporaryDirectory()
                self.addCleanup(temp.cleanup)
                root = Path(temp.name)
                identity = dict(self.identity, workspace=str(root))
                path = create(root, identity, ["f1"])
                event = dict(identity, mcrt=True, role="poster", finding_ids=["f1"], tool_use_id="call-1")
                authorize(path, event)
                if terminate == "abandoned":
                    abandon(path, "operator stopped the run")
                else:
                    record_outcome(path, "call-1", terminate == "completed")
                with self.assertRaises(CheckpointError):
                    record_outcome(path, "call-1", True)

    def test_an_authorization_is_refused_once_the_run_is_terminal(self):
        path = create(self.root, self.identity, ["f1", "f2"])
        authorize(path, self.event("call-1", "f1"))
        record_outcome(path, "call-1", False)
        self.assertFalse(authorize(path, self.event("call-2", "f2")).allowed)


class CheckpointLockTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {
            "workspace": str(self.root), "repository": "acme/widgets",
            "pull_request_id": "42", "binding_digest": "digest",
        }
        self.path = create(self.root, self.identity, ["f1"])
        self.lock = self.path.with_suffix(self.path.suffix + ".lock")

    def test_a_lock_records_its_owner(self):
        self.assertFalse(self.lock.exists())
        authorize(self.path, dict(self.identity, mcrt=True, role="poster", finding_ids=["f1"], tool_use_id="call-1"))
        self.assertFalse(self.lock.exists(), "the lock must be released")

    def test_a_malformed_lock_does_not_wedge_the_run(self):
        self.lock.write_text("", encoding="utf-8")
        abandon(self.path, "operator recovery after a killed hook")
        self.assertEqual(inspect(self.path)["status"], "abandoned")

    def test_a_lock_owned_by_a_dead_process_is_recovered(self):
        dead = 4194303  # above the default pid_max, so it cannot be running
        self.lock.write_text(json.dumps({"pid": dead, "host": os.uname().nodename, "created_at": "2026-01-01T00:00:00+00:00"}), encoding="utf-8")
        abandon(self.path, "operator recovery after a killed hook")
        self.assertEqual(inspect(self.path)["status"], "abandoned")

    def test_a_live_lock_is_preserved(self):
        self.lock.write_text(json.dumps({"pid": os.getpid(), "host": os.uname().nodename, "created_at": "2999-01-01T00:00:00+00:00"}), encoding="utf-8")
        with self.assertRaises(CheckpointError):
            abandon(self.path, "should not steal a live lock")


class GateStatusTest(unittest.TestCase):
    def checkpoint(self, status: str) -> dict:
        return {
            "status": status,
            "identity": {"workspace": "/w", "repository": "a/b", "pull_request_id": "1", "binding_digest": "d"},
            "approved_finding_ids": ["f1"],
            "attempted_finding_ids": [],
        }

    def event(self) -> dict:
        return {
            "mcrt": True, "finding_ids": ["f1"], "workspace": "/w", "repository": "a/b",
            "pull_request_id": "1", "binding_digest": "d", "role": "poster", "tool_use_id": "call-1",
        }

    def test_only_an_approved_checkpoint_authorizes_a_post(self):
        self.assertTrue(evaluate_action(self.checkpoint("approved"), self.event()).allowed)
        for status in ("completed", "failed", "abandoned", "attempting", "running", "pending_approval"):
            with self.subTest(status=status):
                self.assertFalse(evaluate_action(self.checkpoint(status), self.event()).allowed)
