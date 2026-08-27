#!/usr/bin/env python3.12
"""PreToolUse guard for Monolithic Code Review Toolkit pull-request posting.

Converts the poster subagent's prompt-level approval rule into an enforced one.
The Codex adapter can only ask a worker not to post an unapproved finding; this
hook refuses the tool call outright.

Both posting routes are covered: MCP tools whose name looks like a pull-request
comment write, and shell commands that post through a provider CLI (``gh pr
comment``, ``gh api .../comments``, ``az repos pr comment``). A guard that only
knew MCP tool names would be blind on every ``gh``-based provider.

Enforcement is scoped so ordinary manual pull-request comments are unaffected:

- Content carrying an ``[mcrt:<finding-id>]`` marker requires a completed
  checkpoint whose ``approved_finding_ids`` contains every marked id.
- Content carrying no marker is refused only while a checkpoint is mid-run
  (``running``, ``pending_input`` or ``pending_approval``).
- With no checkpoint directory, or no checkpoint mid-run, the hook is inert.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

GUARDED_TOOL_PATTERN = re.compile(
    r"pull_request_thread_write|pull_request_comment|issue_comment|pr_comment",
    re.IGNORECASE,
)
GUARDED_COMMAND_PATTERN = re.compile(
    r"""gh\s+pr\s+(comment|review)
      | gh\s+api\b[^|;]*?/(pulls|issues)/[^|;]*?/comments
      | az\s+repos\s+pr\b[^|;]*?(set-vote|comment)
      | az\s+devops\s+invoke\b[^|;]*?thread
    """,
    re.IGNORECASE | re.VERBOSE,
)
MARKER = re.compile(r"\[mcrt:([A-Za-z0-9._:-]+)\]")
PENDING_STATUSES = {"running", "pending_input", "pending_approval"}
CONTENT_KEYS = ("content", "body", "text", "command")


def is_guarded(tool_name: str, tool_input: dict[str, Any]) -> bool:
    if GUARDED_TOOL_PATTERN.search(tool_name):
        return True
    command = tool_input.get("command")
    return isinstance(command, str) and bool(GUARDED_COMMAND_PATTERN.search(command))


def extract_content(tool_input: dict[str, Any]) -> str:
    return " ".join(
        str(tool_input[key]) for key in CONTENT_KEYS
        if isinstance(tool_input.get(key), str)
    )


def marked_ids(content: str) -> list[str]:
    return sorted(set(MARKER.findall(content)))


def load_checkpoints(workspace: Path) -> list[dict[str, Any]]:
    directory = workspace / ".monolithic-code-review" / "orchestrator"
    if not directory.is_dir():
        return []
    checkpoints = []
    for path in sorted(directory.glob("checkpoint-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            checkpoints.append(value)
    return checkpoints


def approved_ids(checkpoints: list[dict[str, Any]]) -> set[str]:
    approved: set[str] = set()
    for checkpoint in checkpoints:
        if checkpoint.get("status") != "completed":
            continue
        ids = checkpoint.get("approved_finding_ids")
        if isinstance(ids, list):
            approved.update(item for item in ids if isinstance(item, str))
    return approved


def has_run_in_flight(checkpoints: list[dict[str, Any]]) -> bool:
    return any(checkpoint.get("status") in PENDING_STATUSES for checkpoint in checkpoints)


def evaluate(tool_name: str, tool_input: dict[str, Any], workspace: Path) -> str | None:
    if not is_guarded(tool_name, tool_input):
        return None
    checkpoints = load_checkpoints(workspace)
    if not checkpoints:
        return None
    content = extract_content(tool_input)
    ids = marked_ids(content)
    if not ids:
        if has_run_in_flight(checkpoints):
            return (
                "A Monolithic Code Review Toolkit run is in flight and this pull-request "
                "write carries no [mcrt:<finding-id>] marker. Only approved findings may be "
                "posted during a run. Complete the approval step, or post this comment after "
                "the run reaches a terminal state."
            )
        return None
    approved = approved_ids(checkpoints)
    unapproved = sorted(set(ids) - approved)
    if unapproved:
        return (
            f"Refusing to post unapproved review findings: {unapproved}. "
            "A finding may be posted only after the adversarial pass accepts it and the user "
            "approves it, which records its id in a completed checkpoint's approved_finding_ids."
        )
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0
    workspace = Path(payload.get("cwd") or Path.cwd())
    try:
        reason = evaluate(tool_name, tool_input, workspace)
    except OSError:
        return 0
    if reason is None:
        return 0
    print(f"Blocked by mcrt-review poster guard: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
