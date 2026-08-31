"""Registered-write matching, PR derivation and correlation in the Claude guard."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from core.review_harness import contracts as contracts_module
from core.review_harness.checkpoints import create, inspect
from core.review_harness.contracts import binding_digest

ADAPTER = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mcrt_poster_guard_v2", ADAPTER / "mcrt_poster_guard_hook.py")
assert SPEC and SPEC.loader
HOOK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HOOK
SPEC.loader.exec_module(HOOK)

MCP_WRITE = {
    "kind": "mcp_tool", "server": "github", "tool": "post_comment",
    "access": "write", "effect": "scm.comment.create",
}


def sources(**capabilities) -> dict:
    return {
        "version": 2,
        "scm": {
            "owner": "Monolith-INC", "repo": "mcrt",
            "capabilities": capabilities or {"post_inline_comment": MCP_WRITE},
            "unsupported": [],
        },
        "tracker": {"capabilities": {}, "unsupported": []},
    }


def command_write(*args: str) -> dict:
    return {
        "kind": "command", "program": "gh", "args": list(args),
        "access": "write", "effect": "scm.comment.create",
    }


class ClaudeGuardV2Test(unittest.TestCase):
    def workspace(self, document: dict | str | None = None, approved: list[str] | None = None) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        config = root / ".monolithic-code-review"
        config.mkdir(parents=True)
        if document is not None:
            raw = document if isinstance(document, str) else json.dumps(document)
            (config / "sources.json").write_text(raw, encoding="utf-8")
        if approved is not None:
            assert isinstance(document, dict)
            create(root, {
                "workspace": str(root), "repository": "Monolith-INC/mcrt",
                "pull_request_id": "42", "binding_digest": binding_digest(document),
            }, approved)
        return root

    # --- registered writes ---

    def test_a_registered_mcp_write_is_authorized(self):
        root = self.workspace(sources(), ["f1"])
        reason = HOOK.evaluate(
            "mcp__github__post_comment",
            {"body": "the issue [mcrt:f1] is real", "pull_request_id": "42"},
            root,
        )
        self.assertIsNone(reason, reason)

    def test_a_typed_cli_command_derives_its_pull_request_from_the_binding(self):
        document = sources(post_summary_comment=command_write("pr", "comment", "{pull_request_id}", "--body", "{body}"))
        root = self.workspace(document, ["f1"])
        reason = HOOK.evaluate(
            "Bash",
            {"command": "gh pr comment 42 --body 'the issue [mcrt:f1] is real'"},
            root,
        )
        self.assertIsNone(reason, reason)

    def test_a_typed_cli_command_for_another_pull_request_is_denied(self):
        document = sources(post_summary_comment=command_write("pr", "comment", "{pull_request_id}", "--body", "{body}"))
        root = self.workspace(document, ["f1"])
        reason = HOOK.evaluate(
            "Bash",
            {"command": "gh pr comment 43 --body 'the issue [mcrt:f1] is real'"},
            root,
        )
        self.assertIsNotNone(reason)

    def test_a_marker_inside_the_bound_body_file_is_found(self):
        document = sources(post_summary_comment=command_write("pr", "comment", "{pull_request_id}", "--body-file", "{body_file}"))
        root = self.workspace(document, ["f1"])
        body = root / "comment.md"
        body.write_text("A longer comment.\n\n[mcrt:f1]\n", encoding="utf-8")
        reason = HOOK.evaluate("Bash", {"command": f"gh pr comment 42 --body-file {body}"}, root)
        self.assertIsNone(reason, reason)

    def test_an_unregistered_provider_cli_is_still_gated(self):
        root = self.workspace(sources(), ["f1"])
        reason = HOOK.evaluate("Bash", {"command": "gh pr comment 42 --body 'sneaking [mcrt:f9] in'"}, root)
        self.assertIsNotNone(reason, "an unapproved finding was posted by shelling out")

    # --- scope ---

    def test_a_local_write_carrying_a_marker_is_not_blocked(self):
        root = self.workspace(sources(), ["f1"])
        reason = HOOK.evaluate(
            "Write",
            {"file_path": str(root / "report.md"), "content": "Finding [mcrt:f1] is real"},
            root,
        )
        self.assertIsNone(reason, reason)

    def test_an_unmarked_registered_write_is_denied_while_a_run_is_in_flight(self):
        root = self.workspace(sources(), ["f1"])
        reason = HOOK.evaluate(
            "mcp__github__post_comment", {"body": "a manual note", "pull_request_id": "42"}, root,
        )
        self.assertIsNotNone(reason)

    def test_an_unmarked_registered_write_is_allowed_with_no_run_in_flight(self):
        root = self.workspace(sources())
        reason = HOOK.evaluate(
            "mcp__github__post_comment", {"body": "a manual note", "pull_request_id": "42"}, root,
        )
        self.assertIsNone(reason, reason)

    def test_a_malformed_v2_document_denies_a_guarded_write(self):
        root = self.workspace('{"version": 2, "scm": {"capabilities": 5, "unsupported": []}, "tracker": {}}')
        reason = HOOK.evaluate(
            "mcp__github__post_comment", {"body": "[mcrt:f1]", "pull_request_id": "42"}, root,
        )
        self.assertIsNotNone(reason, "a malformed v2 document must fail closed")

    def test_a_malformed_v2_document_denies_a_review_creation_write(self):
        root = self.workspace('{"version": 2, "scm": {"capabilities": 5, "unsupported": []}, "tracker": {}}')
        reason = HOOK.evaluate(
            "mcp__github__create_review", {"body": "ordinary review", "pull_request_id": "42"}, root,
        )
        self.assertIsNotNone(reason, "a malformed v2 document must fail closed for review creation")

    def test_a_malformed_v2_document_leaves_ordinary_work_alone(self):
        root = self.workspace('{"version": 2, "scm": {"capabilities": 5, "unsupported": []}, "tracker": {}}')
        self.assertIsNone(HOOK.evaluate("Read", {"file_path": "README.md"}, root))

    # --- hot path ---

    def test_one_gated_call_validates_the_document_once(self):
        calls = []
        real = contracts_module.validate_sources

        def counting(value):
            calls.append(value)
            return real(value)

        root = self.workspace(sources(), ["f1"])
        HOOK.validate_sources = counting
        contracts_module.validate_sources = counting
        try:
            HOOK.evaluate(
                "mcp__github__post_comment",
                {"body": "the issue [mcrt:f1] is real", "pull_request_id": "42"},
                root,
            )
        finally:
            HOOK.validate_sources = real
            contracts_module.validate_sources = real
        self.assertEqual(len(calls), 1, f"validated {len(calls)} times for one tool call")

    # --- correlation ---

    def post_event(self, root: Path, tool_input: dict, **overrides) -> dict:
        return {
            "hook_event_name": "PostToolUse", "cwd": str(root),
            "tool_name": "mcp__github__post_comment", "tool_input": tool_input,
            "tool_response": {"id": 1}, **overrides,
        }

    def run_main(self, payload: dict) -> int:
        original = sys.stdin
        sys.stdin = StringIO(json.dumps(payload))
        try:
            return HOOK.main()
        finally:
            sys.stdin = original

    def test_two_findings_can_be_posted_in_separate_calls(self):
        root = self.workspace(sources(), ["f1", "f2"])
        first = {"body": "one [mcrt:f1]", "pull_request_id": "42"}
        second = {"body": "two [mcrt:f2]", "pull_request_id": "42"}
        self.assertIsNone(HOOK.evaluate("mcp__github__post_comment", first, root))
        self.run_main(self.post_event(root, first))
        self.assertIsNone(HOOK.evaluate("mcp__github__post_comment", second, root))
        self.run_main(self.post_event(root, second))
        path = next((root / ".monolithic-code-review" / "orchestrator").glob("checkpoint-*.json"))
        checkpoint = inspect(path)
        self.assertEqual(checkpoint["status"], "completed")
        self.assertEqual(len(checkpoint["post_outcomes"]), 2)

    def test_a_failed_response_fails_the_run(self):
        root = self.workspace(sources(), ["f1"])
        tool_input = {"body": "one [mcrt:f1]", "pull_request_id": "42"}
        self.assertIsNone(HOOK.evaluate("mcp__github__post_comment", tool_input, root))
        self.run_main(self.post_event(root, tool_input, tool_response={"error": "permission denied"}))
        path = next((root / ".monolithic-code-review" / "orchestrator").glob("checkpoint-*.json"))
        self.assertEqual(inspect(path)["status"], "failed")

    def test_an_unrelated_post_event_is_ignored(self):
        root = self.workspace(sources(), ["f1"])
        tool_input = {"body": "one [mcrt:f1]", "pull_request_id": "42"}
        self.assertIsNone(HOOK.evaluate("mcp__github__post_comment", tool_input, root))
        self.run_main({
            "hook_event_name": "PostToolUse", "cwd": str(root), "tool_name": "Read",
            "tool_input": {"file_path": "README.md"}, "tool_response": {"error": "not found"},
        })
        path = next((root / ".monolithic-code-review" / "orchestrator").glob("checkpoint-*.json"))
        checkpoint = inspect(path)
        self.assertEqual(checkpoint["post_outcomes"], [])
        self.assertEqual(checkpoint["status"], "approved")


if __name__ == "__main__":
    unittest.main()
