from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1]
HOOK_PATH = ADAPTER / "mcrt_poster_guard_hook.py"

_spec = importlib.util.spec_from_file_location("mcrt_poster_guard_hook", HOOK_PATH)
assert _spec is not None and _spec.loader is not None
HOOK = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = HOOK
_spec.loader.exec_module(HOOK)

MCP_TOOL = "mcp__azure-devops__repo_pull_request_thread_write"


def workspace_with(tmp: str, status: str, approved: list[str]) -> Path:
    workspace = Path(tmp)
    directory = workspace / ".monolithic-code-review" / "orchestrator"
    directory.mkdir(parents=True)
    (directory / "checkpoint-test.json").write_text(
        json.dumps({"status": status, "approved_finding_ids": approved}), encoding="utf-8",
    )
    return workspace


class GuardedDetectionTest(unittest.TestCase):
    def test_detects_mcp_thread_write_tools(self):
        for name in (MCP_TOOL, "mcp__github__create_pull_request_comment", "some_pr_comment_tool"):
            self.assertTrue(HOOK.is_guarded(name, {}), name)

    def test_detects_cli_posting_commands(self):
        for command in (
            "gh pr comment 42 --body-file /tmp/body.md",
            "gh api repos/o/r/pulls/42/comments -f body=hi",
            "az repos pr comment --id 42",
            "az devops invoke --area git --resource pullRequestThreads",
        ):
            self.assertTrue(HOOK.is_guarded("Bash", {"command": command}), command)

    def test_ignores_ordinary_tools_and_commands(self):
        self.assertFalse(HOOK.is_guarded("Read", {}))
        self.assertFalse(HOOK.is_guarded("Bash", {"command": "gh pr view 42"}))
        self.assertFalse(HOOK.is_guarded("Bash", {"command": "git diff --stat"}))


class EvaluationTest(unittest.TestCase):
    def evaluate(self, workspace, content, tool=MCP_TOOL, key="content"):
        return HOOK.evaluate(tool, {key: content}, workspace)

    def test_allows_approved_marked_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = workspace_with(tmp, "completed", ["finding-1"])
            self.assertIsNone(self.evaluate(workspace, "Problem [mcrt:finding-1]"))

    def test_blocks_unapproved_marked_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = workspace_with(tmp, "completed", ["finding-1"])
            reason = self.evaluate(workspace, "Sneaky [mcrt:finding-9]")
        self.assertIsNotNone(reason)
        self.assertIn("finding-9", reason)

    def test_blocks_when_any_marked_id_is_unapproved(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = workspace_with(tmp, "completed", ["finding-1"])
            reason = self.evaluate(workspace, "[mcrt:finding-1] and [mcrt:finding-2]")
        self.assertIn("finding-2", reason)

    def test_blocks_unmarked_write_while_run_in_flight(self):
        for status in ("running", "pending_input", "pending_approval"):
            with tempfile.TemporaryDirectory() as tmp:
                workspace = workspace_with(tmp, status, [])
                self.assertIsNotNone(self.evaluate(workspace, "plain comment"), status)

    def test_blocks_marked_write_before_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = workspace_with(tmp, "pending_approval", [])
            self.assertIsNotNone(self.evaluate(workspace, "early [mcrt:finding-1]"))

    def test_allows_unmarked_write_when_no_run_in_flight(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = workspace_with(tmp, "completed", ["finding-1"])
            self.assertIsNone(self.evaluate(workspace, "an ordinary manual comment"))

    def test_inert_without_checkpoint_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self.evaluate(Path(tmp), "plain comment"))

    def test_guards_cli_posting_through_the_command_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = workspace_with(tmp, "completed", ["finding-1"])
            blocked = HOOK.evaluate(
                "Bash", {"command": "gh pr comment 42 --body '[mcrt:finding-9]'"}, workspace,
            )
            allowed = HOOK.evaluate(
                "Bash", {"command": "gh pr comment 42 --body '[mcrt:finding-1]'"}, workspace,
            )
        self.assertIsNotNone(blocked)
        self.assertIsNone(allowed)

    def test_ignores_malformed_checkpoint_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = workspace_with(tmp, "completed", ["finding-1"])
            bad = workspace / ".monolithic-code-review" / "orchestrator" / "checkpoint-bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertIsNone(self.evaluate(workspace, "[mcrt:finding-1]"))


class ProcessContractTest(unittest.TestCase):
    def run_hook(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=json.dumps(payload), capture_output=True, text=True, check=False,
        )

    def test_exits_two_and_explains_when_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = workspace_with(tmp, "completed", ["finding-1"])
            result = self.run_hook({
                "tool_name": MCP_TOOL, "cwd": str(workspace),
                "tool_input": {"content": "[mcrt:finding-9]"},
            })
        self.assertEqual(result.returncode, 2)
        self.assertIn("finding-9", result.stderr)

    def test_exits_zero_when_allowing(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = workspace_with(tmp, "completed", ["finding-1"])
            result = self.run_hook({
                "tool_name": MCP_TOOL, "cwd": str(workspace),
                "tool_input": {"content": "[mcrt:finding-1]"},
            })
        self.assertEqual(result.returncode, 0)

    def test_malformed_stdin_does_not_block(self):
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input="not json", capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0)

    def test_missing_fields_do_not_block(self):
        self.assertEqual(self.run_hook({}).returncode, 0)
        self.assertEqual(self.run_hook({"tool_name": MCP_TOOL}).returncode, 0)


if __name__ == "__main__":
    unittest.main()
