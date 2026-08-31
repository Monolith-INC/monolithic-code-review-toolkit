"""Provenance, identity and correlation behaviour of the Codex review hook."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from core.review_harness.checkpoints import create, inspect
from core.review_harness.contracts import binding_digest

ADAPTER = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mcrt_review_hook_provenance", ADAPTER / "mcrt_review_hook.py")
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


class CodexProvenanceTest(unittest.TestCase):
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

    def payload(self, root: Path, **overrides) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "cwd": str(root),
            "agent_type": "mcrt_review_poster",
            "tool_name": "mcp__github__post_comment",
            "tool_use_id": "call-1",
            "tool_input": {"body": "Looks wrong here. [mcrt:finding-1]", "pull_request_id": "42"},
            **overrides,
        }

    # --- provenance ---

    def test_a_marker_in_the_posted_content_authorizes_the_post(self):
        root = self.workspace(sources(), ["finding-1"])
        self.assertIsNone(HOOK.evaluate(self.payload(root)))

    def test_metadata_cannot_stand_in_for_the_posted_content(self):
        """A volunteered mcrt_finding_ids field is not provenance: the real
        content carries no marker, so the write is unapproved during a run."""
        root = self.workspace(sources(), ["finding-1"])
        payload = self.payload(root, tool_input={
            "mcrt_finding_ids": ["finding-1"], "body": "no marker here", "pull_request_id": "42",
        })
        self.assertIsNotNone(HOOK.evaluate(payload))

    def test_metadata_disagreeing_with_the_content_is_ignored(self):
        root = self.workspace(sources(), ["finding-1"])
        payload = self.payload(root, tool_input={
            "mcrt_finding_ids": ["finding-1"],
            "body": "different finding [mcrt:finding-9]",
            "pull_request_id": "42",
        })
        reason = HOOK.evaluate(payload)
        self.assertIsNotNone(reason)
        self.assertIn("unapproved", reason)

    def test_a_command_post_is_authorized_through_its_binding(self):
        document = sources(post_summary_comment=command_write("pr", "comment", "{pull_request_id}", "--body", "{body}"))
        root = self.workspace(document, ["finding-1"])
        payload = self.payload(root, tool_name="Bash", tool_input={
            "command": "gh pr comment 42 --body 'fix this [mcrt:finding-1]'",
        })
        self.assertIsNone(HOOK.evaluate(payload))

    def test_a_command_post_for_another_pull_request_is_denied(self):
        document = sources(post_summary_comment=command_write("pr", "comment", "{pull_request_id}", "--body", "{body}"))
        root = self.workspace(document, ["finding-1"])
        payload = self.payload(root, tool_name="Bash", tool_input={
            "command": "gh pr comment 43 --body 'fix this [mcrt:finding-1]'",
        })
        self.assertIsNotNone(HOOK.evaluate(payload))

    def test_a_marker_inside_the_bound_body_file_is_found(self):
        document = sources(post_summary_comment=command_write("pr", "comment", "{pull_request_id}", "--body-file", "{body_file}"))
        root = self.workspace(document, ["finding-1"])
        body = root / "comment.md"
        body.write_text("A longer review comment.\n\n[mcrt:finding-1]\n", encoding="utf-8")
        payload = self.payload(root, tool_name="Bash", tool_input={
            "command": f"gh pr comment 42 --body-file {body}",
        })
        self.assertIsNone(HOOK.evaluate(payload))

    # --- scope ---

    def test_a_local_write_carrying_a_marker_is_not_blocked(self):
        root = self.workspace(sources(), ["finding-1"])
        payload = self.payload(root, tool_name="Write", tool_input={
            "file_path": str(root / "notes.md"), "content": "todo: [mcrt:finding-9]",
        })
        self.assertIsNone(HOOK.evaluate(payload))

    def test_an_unmarked_registered_write_is_denied_while_a_run_is_in_flight(self):
        root = self.workspace(sources(), ["finding-1"])
        payload = self.payload(root, tool_input={"body": "a manual comment", "pull_request_id": "42"})
        self.assertIsNotNone(HOOK.evaluate(payload))

    def test_an_unmarked_registered_write_is_allowed_with_no_run_in_flight(self):
        root = self.workspace(sources())
        payload = self.payload(root, tool_input={"body": "a manual comment", "pull_request_id": "42"})
        self.assertIsNone(HOOK.evaluate(payload))

    def test_an_unconfigured_workspace_is_inert(self):
        root = self.workspace()
        self.assertIsNone(HOOK.evaluate(self.payload(root)))

    def test_a_v1_document_is_left_to_the_legacy_path(self):
        root = self.workspace({"version": 1, "scm": {"capabilities": {}}, "tracker": {"capabilities": {}}})
        self.assertIsNone(HOOK.evaluate(self.payload(root)))

    def test_a_malformed_v2_document_denies_a_marked_write(self):
        root = self.workspace('{"version": 2, "scm": {"capabilities": 5, "unsupported": []}, "tracker": {}}')
        reason = HOOK.evaluate(self.payload(root))
        self.assertIsNotNone(reason, "a malformed v2 document must fail closed")

    def test_a_malformed_v2_document_leaves_ordinary_work_alone(self):
        root = self.workspace('{"version": 2, "scm": {"capabilities": 5, "unsupported": []}, "tracker": {}}')
        payload = self.payload(root, tool_name="Read", tool_input={"file_path": "README.md"})
        self.assertIsNone(HOOK.evaluate(payload))

    # --- identity ---

    def test_a_non_poster_agent_cannot_consume_an_approval(self):
        root = self.workspace(sources(), ["finding-1"])
        reason = HOOK.evaluate(self.payload(root, agent_type="mcrt_review_validator"))
        self.assertIsNotNone(reason, "a non-poster agent consumed an approval")

    def test_an_absent_agent_identity_cannot_consume_an_approval(self):
        root = self.workspace(sources(), ["finding-1"])
        payload = self.payload(root)
        payload.pop("agent_type")
        self.assertIsNotNone(HOOK.evaluate(payload))

    def test_a_marked_write_without_a_tool_use_id_is_denied(self):
        root = self.workspace(sources(), ["finding-1"])
        payload = self.payload(root)
        payload.pop("tool_use_id")
        self.assertIsNotNone(HOOK.evaluate(payload))

    # --- correlation ---

    def run_main(self, payload: dict) -> int:
        original = sys.stdin
        sys.stdin = StringIO(json.dumps(payload))
        try:
            return HOOK.main()
        finally:
            sys.stdin = original

    def authorized(self) -> tuple[Path, Path]:
        document = sources()
        root = self.workspace(document, ["finding-1"])
        self.assertIsNone(HOOK.evaluate(self.payload(root)))
        path = HOOK._checkpoint(root)
        assert path is not None
        return root, path

    def test_a_successful_response_completes_the_authorized_post(self):
        root, path = self.authorized()
        self.run_main({
            "hook_event_name": "PostToolUse", "cwd": str(root), "tool_use_id": "call-1",
            "tool_name": "mcp__github__post_comment", "tool_response": {"id": 1},
        })
        self.assertEqual(inspect(path)["status"], "completed")

    def test_a_failed_response_fails_the_authorized_post(self):
        root, path = self.authorized()
        self.run_main({
            "hook_event_name": "PostToolUse", "cwd": str(root), "tool_use_id": "call-1",
            "tool_name": "mcp__github__post_comment", "tool_response": {"error": "permission denied"},
        })
        checkpoint = inspect(path)
        self.assertEqual(checkpoint["status"], "failed")
        self.assertFalse(checkpoint["post_outcomes"][-1]["succeeded"])

    def test_an_unrelated_post_event_is_ignored(self):
        root, path = self.authorized()
        self.run_main({
            "hook_event_name": "PostToolUse", "cwd": str(root), "tool_use_id": "an-unrelated-read",
            "tool_name": "Read", "tool_response": {"error": "file not found"},
        })
        checkpoint = inspect(path)
        self.assertEqual(checkpoint["post_outcomes"], [])
        self.assertEqual(checkpoint["status"], "approved")


if __name__ == "__main__":
    unittest.main()
