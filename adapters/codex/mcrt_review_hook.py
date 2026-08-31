#!/usr/bin/env python3.12
"""Codex PreToolUse/PostToolUse translation for the core MCRT action gate.

Provenance comes from what is actually being posted — an ``[mcrt:<id>]`` marker
in the content, in a matched command's arguments, or in the body file that
command names — never from a metadata field the calling agent volunteers. A
marked write is matched against a registered write capability first, so ordinary
local edits and unmarked manual comments outside a run are untouched.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.review_harness.checkpoints import CheckpointError, find_active_checkpoint, record_outcome, authorize
from core.review_harness.contracts import ContractError, binding_digest, match_command_binding, validate_sources

MARKER = re.compile(r"\[mcrt:([A-Za-z0-9._:-]+)\]")
CONTENT_KEYS = ("body", "content", "text", "comment", "message", "command")
PR_INPUT_KEYS = ("pull_request_id", "pull_number", "pr")
# Used only to decide whether a *malformed* v2 document must fail closed, where
# no binding can be matched.
COMMENT_TOOL = re.compile(r"pull_request|pr_comment|issue_comment|review_thread|post_comment", re.IGNORECASE)
BODY_FILE_LIMIT = 262144


class HookError(RuntimeError):
    """The configuration cannot be trusted, so a guarded write must be denied."""


def _sources(workspace: Path) -> dict[str, Any] | None:
    """Return the validated v2 document, or None when the project is not on v2.

    A present-but-invalid v2 document is not "unconfigured": it raises, so the
    caller can fail closed instead of treating the hook as inert.
    """
    path = workspace / ".monolithic-code-review" / "sources.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HookError(f"unreadable review sources document: {error}") from error
    if not isinstance(raw, dict) or raw.get("version") != 2:
        return None
    try:
        return validate_sources(raw)
    except ContractError as error:
        raise HookError(f"invalid v2 review sources document: {error}") from error


def _checkpoint(workspace: Path) -> Path | None:
    return find_active_checkpoint(workspace)


def _marked_ids(*values: str) -> list[str]:
    found: set[str] = set()
    for value in values:
        found.update(MARKER.findall(value))
    return sorted(found)


def _input_content(tool_input: dict[str, Any]) -> list[str]:
    return [str(tool_input[key]) for key in CONTENT_KEYS if isinstance(tool_input.get(key), str)]


def _body_file_content(workspace: Path, captured: dict[str, str]) -> list[str]:
    reference = captured.get("body_file")
    if not reference:
        return []
    path = Path(reference)
    if not path.is_absolute():
        path = workspace / path
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return [handle.read(BODY_FILE_LIMIT)]
    except OSError:
        return []


def _write_bindings(sources: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        binding for binding in sources["scm"].get("capabilities", {}).values()
        if binding.get("access") == "write"
    ]


def _match_write(workspace: Path, sources: dict[str, Any], tool_name: str, tool_input: dict[str, Any]) -> tuple[bool, list[str], str]:
    """Match this call against a registered write capability.

    Returns whether a binding matched, the finding ids the real content carries,
    and the pull request the call targets.
    """
    for binding in _write_bindings(sources):
        if binding.get("kind") == "mcp_tool":
            if tool_name != f"mcp__{binding['server']}__{binding['tool']}":
                continue
            pull_request_id = next(
                (str(tool_input[key]) for key in PR_INPUT_KEYS if tool_input.get(key) not in (None, "")),
                "",
            )
            return True, _marked_ids(*_input_content(tool_input)), pull_request_id
        if binding.get("kind") == "command":
            command = tool_input.get("command")
            if not isinstance(command, str) or not command.strip():
                continue
            try:
                argv = shlex.split(command)
            except ValueError:
                continue
            captured = match_command_binding(binding, argv)
            if captured is None:
                continue
            content = [command, *_body_file_content(workspace, captured), *captured.values()]
            return True, _marked_ids(*content), captured.get("pull_request_id", "")
    return False, [], ""


def _role(payload: dict[str, Any]) -> str:
    """Never collapse "not the poster" into "no identity available"."""
    agent = payload.get("agent_type")
    if agent == "mcrt_review_poster":
        return "poster"
    if isinstance(agent, str) and agent.strip():
        return agent.strip()
    return "unknown"


def _guarded_surface(tool_name: str, tool_input: dict[str, Any]) -> bool:
    if COMMENT_TOOL.search(tool_name):
        return True
    return bool(_marked_ids(*_input_content(tool_input)))


def evaluate(payload: dict[str, Any]) -> str | None:
    workspace = Path(payload.get("cwd", ""))
    if not workspace.is_absolute():
        return None
    tool_input = payload.get("tool_input")
    tool_name = str(payload.get("tool_name", ""))
    if not isinstance(tool_input, dict):
        return None
    try:
        sources = _sources(workspace)
    except HookError as error:
        return str(error) if _guarded_surface(tool_name, tool_input) else None
    if sources is None:
        return None
    matched, ids, pull_request_id = _match_write(workspace, sources, tool_name, tool_input)
    if not matched:
        return None
    try:
        path = _checkpoint(workspace)
    except CheckpointError as error:
        return str(error)
    if not ids:
        if path is None:
            return None
        return (
            "A review run is in flight and this pull-request write carries no "
            "[mcrt:<finding-id>] marker. Only approved findings may be posted during a run."
        )
    if path is None:
        return "MCRT-marked action has no approval checkpoint"
    repository = f"{sources['scm'].get('owner', '')}/{sources['scm'].get('repo', '')}".strip("/")
    event = {
        "mcrt": True, "role": _role(payload), "finding_ids": ids,
        "workspace": str(workspace), "repository": repository,
        "pull_request_id": pull_request_id,
        "binding_digest": binding_digest(sources, prevalidated=True),
        "tool_use_id": payload.get("tool_use_id"),
    }
    try:
        decision = authorize(path, event)
    except CheckpointError as error:
        return str(error)
    return None if decision.allowed else decision.reason


def _succeeded(payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Read the host's own report of what happened, not the mere fact of an event."""
    if payload.get("hook_event_name") == "PostToolUseFailure":
        return False, "host reported a tool failure"
    response = payload.get("tool_response")
    if isinstance(response, dict):
        for key in ("error", "error_message", "stderr"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return False, value.strip()[:200]
            if value:
                return False, str(key)
        if response.get("is_error") or response.get("success") is False:
            return False, "provider reported an error"
        status = response.get("status_code", response.get("status"))
        if isinstance(status, int) and not 200 <= status < 300:
            return False, f"provider returned status {status}"
        exit_code = response.get("exit_code", response.get("returncode"))
        if isinstance(exit_code, int) and exit_code != 0:
            return False, f"command exited with {exit_code}"
    return True, None


def _record(payload: dict[str, Any]) -> int:
    workspace = Path(payload.get("cwd", ""))
    tool_use_id = payload.get("tool_use_id")
    if not workspace.is_absolute() or not isinstance(tool_use_id, str) or not tool_use_id:
        return 0
    try:
        path = _checkpoint(workspace)
        if path is None:
            return 0
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        pending = checkpoint.get("pending_posts")
        if not isinstance(pending, dict) or tool_use_id not in pending:
            return 0
        succeeded, detail = _succeeded(payload)
        record_outcome(path, tool_use_id, succeeded, detail)
    except (OSError, json.JSONDecodeError, CheckpointError):
        return 2
    return 0


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("hook_event_name") in {"PostToolUse", "PostToolUseFailure"}:
        return _record(payload)
    if payload.get("hook_event_name") != "PreToolUse":
        return 0
    reason = evaluate(payload)
    if reason is None:
        return 0
    print(f"Blocked by MCRT deterministic action gate: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
