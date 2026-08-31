from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from core.review_harness.checkpoints import create
from core.review_harness.contracts import binding_digest

ADAPTER = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mcrt_review_hook", ADAPTER / "mcrt_review_hook.py")
assert SPEC and SPEC.loader
HOOK = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HOOK
SPEC.loader.exec_module(HOOK)


def sources() -> dict:
    return {"version": 2, "scm": {"owner": "Monolith-INC", "repo": "mcrt", "capabilities": {
        "post_inline_comment": {"kind": "mcp_tool", "server": "github", "tool": "post_comment", "access": "write", "effect": "scm.comment.create"},
    }, "unsupported": []}, "tracker": {"capabilities": {}, "unsupported": []}}


class CodexHookTest(unittest.TestCase):
    def test_consumes_a_matching_approval_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / ".monolithic-code-review").mkdir()
            value = sources()
            (workspace / ".monolithic-code-review" / "sources.json").write_text(json.dumps(value), encoding="utf-8")
            identity = {"workspace": str(workspace), "repository": "Monolith-INC/mcrt", "pull_request_id": "42", "binding_digest": binding_digest(value)}
            create(workspace, identity, ["finding-1"])
            payload = {"hook_event_name": "PreToolUse", "cwd": str(workspace), "agent_type": "mcrt_review_poster", "tool_name": "mcp__github__post_comment", "tool_use_id": "call-1", "tool_input": {"body": "review comment [mcrt:finding-1]", "pull_request_id": "42"}}
            self.assertIsNone(HOOK.evaluate(payload))
            self.assertIsNotNone(HOOK.evaluate(payload))

    def test_post_tool_hook_records_the_authorized_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / ".monolithic-code-review").mkdir()
            value = sources()
            (workspace / ".monolithic-code-review" / "sources.json").write_text(json.dumps(value), encoding="utf-8")
            identity = {"workspace": str(workspace), "repository": "Monolith-INC/mcrt", "pull_request_id": "42", "binding_digest": binding_digest(value)}
            path = create(workspace, identity, ["finding-1"])
            pre = {"hook_event_name": "PreToolUse", "cwd": str(workspace), "agent_type": "mcrt_review_poster", "tool_name": "mcp__github__post_comment", "tool_use_id": "call-1", "tool_input": {"body": "review comment [mcrt:finding-1]", "pull_request_id": "42"}}
            self.assertIsNone(HOOK.evaluate(pre))
            old_stdin = sys.stdin
            try:
                from io import StringIO
                sys.stdin = StringIO(json.dumps({"hook_event_name": "PostToolUse", "cwd": str(workspace), "tool_use_id": "call-1"}))
                self.assertEqual(HOOK.main(), 0)
            finally:
                sys.stdin = old_stdin
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "completed")

    def test_is_inert_for_unmarked_or_unconfigured_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"hook_event_name": "PreToolUse", "cwd": tmp, "tool_name": "Read", "tool_input": {}}
            self.assertIsNone(HOOK.evaluate(payload))


if __name__ == "__main__":
    unittest.main()
