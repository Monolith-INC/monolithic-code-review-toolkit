from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from core.review_harness.checkpoints import CheckpointError, abandon, authorize, create, inspect, record_outcome, resume
from core.review_harness.contracts import ContractError, binding_digest, migrate_sources_v1, validate_sources
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
