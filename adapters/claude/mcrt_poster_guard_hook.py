#!/usr/bin/env python3.12
"""PreToolUse/PostToolUse guard for Monolithic Code Review Toolkit posting.

Converts the poster subagent's prompt-level approval rule into an enforced one.
The orchestrator can only ask a worker not to post an unapproved finding; this
hook refuses the tool call outright.

On a project using ``sources.json`` v2 the guarded surface is the set of
registered write capabilities: an MCP tool by name, or a command whose argv
matches its binding template, from which the pull request id and body file are
captured. A provider CLI that posts while the project is on v2 is gated even if
it matches no binding, so the gate cannot be bypassed by shelling out.

Enforcement is scoped so ordinary work is unaffected:

- The tool is matched first, then its content. A local file that merely mentions
  an ``[mcrt:<finding-id>]`` marker is not a pull-request write.
- A marked write requires an approved checkpoint that binds this workspace,
  repository, pull request and binding digest, and that has not already
  attempted the marked findings.
- An unmarked registered write is refused only while a run is in flight.
- With no configuration, or no checkpoint, the hook is inert.

Projects still on v1 keep the original marker-versus-completed-checkpoint
behaviour below.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.review_harness.checkpoints import (
    CheckpointError,
    authorize,
    find_active_checkpoint,
    record_outcome,
)
from core.review_harness.contracts import (
    ContractError,
    binding_digest,
    match_command_binding,
    validate_sources,
)

GUARDED_TOOL_PATTERN = re.compile(
    r"pull_request_thread_write|pull_request_comment|issue_comment|pr_comment|post_comment",
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
PULL_REQUEST_IN_URL = re.compile(r"/(?:pulls|pullrequests|pullRequests)/(\d+)")
PULL_REQUEST_FLAG = re.compile(r"--(?:pr|pull-request|pull-request-id|id)(?:=|\s+)(\d+)")
PENDING_STATUSES = {"running", "pending_input", "pending_approval"}
CONTENT_KEYS = ("content", "body", "text", "command")
PR_INPUT_KEYS = ("pull_request_id", "pull_number", "pr")
BODY_FILE_LIMIT = 262144


class HookError(RuntimeError):
    """The configuration cannot be trusted, so a guarded write must be denied."""


@dataclass(frozen=True)
class WriteMatch:
    """One registered — or fail-closed — external write the gate must decide."""

    ids: list[str]
    pull_request_id: str = ""
    captured: dict[str, str] = field(default_factory=dict)


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


def _v2_sources(workspace: Path) -> dict[str, Any] | None:
    """Return the validated v2 document, or None when the project is not on v2.

    A present-but-invalid v2 document raises, so a guarded write fails closed
    instead of falling through to the v1 path or being treated as unconfigured.
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


def _body_file_content(workspace: Path, reference: str | None) -> str:
    if not reference:
        return ""
    path = Path(reference)
    if not path.is_absolute():
        path = workspace / path
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(BODY_FILE_LIMIT)
    except OSError:
        return ""


def _pull_request_from_argv(argv: list[str], command: str) -> str:
    """Best-effort pull request id for a provider CLI with no binding template."""
    in_url = PULL_REQUEST_IN_URL.search(command)
    if in_url:
        return in_url.group(1)
    flagged = PULL_REQUEST_FLAG.search(command)
    if flagged:
        return flagged.group(1)
    for token in argv[1:]:
        if token.isdigit():
            return token
    return ""


def _match_write(
    workspace: Path, sources: dict[str, Any], tool_name: str, tool_input: dict[str, Any]
) -> WriteMatch | None:
    """Match the tool first, then read the content it is actually posting."""
    for binding in sources["scm"].get("capabilities", {}).values():
        if binding.get("access") != "write":
            continue
        if binding.get("kind") == "mcp_tool":
            if tool_name != f"mcp__{binding['server']}__{binding['tool']}":
                continue
            pull_request_id = next(
                (str(tool_input[key]) for key in PR_INPUT_KEYS if tool_input.get(key) not in (None, "")),
                "",
            )
            return WriteMatch(marked_ids(extract_content(tool_input)), pull_request_id)
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
            content = " ".join([
                command,
                _body_file_content(workspace, captured.get("body_file")),
                *captured.values(),
            ])
            return WriteMatch(marked_ids(content), captured.get("pull_request_id", ""), captured)

    # No binding matched. A provider CLI that posts is still gated while the
    # project is on v2, so shelling out cannot bypass the approval contract.
    command = tool_input.get("command")
    if isinstance(command, str) and GUARDED_COMMAND_PATTERN.search(command):
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = command.split()
        return WriteMatch(marked_ids(command), _pull_request_from_argv(argv, command))
    if GUARDED_TOOL_PATTERN.search(tool_name):
        pull_request_id = next(
            (str(tool_input[key]) for key in PR_INPUT_KEYS if tool_input.get(key) not in (None, "")),
            "",
        )
        return WriteMatch(marked_ids(extract_content(tool_input)), pull_request_id)
    return None


def call_fingerprint(tool_name: str, tool_input: dict[str, Any]) -> str:
    """A correlation id for hosts that do not expose one.

    Derived from the call itself, so the PostToolUse event for the same tool call
    resolves to the same authorization and an unrelated call never does.
    """
    material = json.dumps([tool_name, tool_input], sort_keys=True, default=str).encode("utf-8")
    return f"claude-call-{hashlib.sha256(material).hexdigest()[:32]}"


def _evaluate_v2(
    tool_name: str,
    tool_input: dict[str, Any],
    workspace: Path,
    sources: dict[str, Any],
    tool_use_id: str | None,
) -> str | None:
    match = _match_write(workspace, sources, tool_name, tool_input)
    if match is None:
        return None
    try:
        path = find_active_checkpoint(workspace)
    except CheckpointError as error:
        return str(error)
    if not match.ids:
        if path is None:
            return None
        return (
            "A Monolithic Code Review Toolkit run is in flight and this pull-request "
            "write carries no [mcrt:<finding-id>] marker. Only approved findings may be "
            "posted during a run. Complete the approval step, or post this comment after "
            "the run reaches a terminal state."
        )
    if path is None:
        return "MCRT-marked action has no approval checkpoint"
    repository = f"{sources['scm'].get('owner', '')}/{sources['scm'].get('repo', '')}".strip("/")
    event = {
        "mcrt": True,
        "finding_ids": match.ids,
        "workspace": str(workspace),
        "repository": repository,
        "pull_request_id": match.pull_request_id,
        "binding_digest": binding_digest(sources, prevalidated=True),
        "tool_use_id": tool_use_id or call_fingerprint(tool_name, tool_input),
    }
    try:
        decision = authorize(path, event)
    except CheckpointError as error:
        return str(error)
    return None if decision.allowed else decision.reason


def _evaluate_v1(tool_name: str, tool_input: dict[str, Any], workspace: Path) -> str | None:
    if not is_guarded(tool_name, tool_input):
        return None
    checkpoints = load_checkpoints(workspace)
    if not checkpoints:
        return None
    ids = marked_ids(extract_content(tool_input))
    if not ids:
        if has_run_in_flight(checkpoints):
            return (
                "A Monolithic Code Review Toolkit run is in flight and this pull-request "
                "write carries no [mcrt:<finding-id>] marker. Only approved findings may be "
                "posted during a run. Complete the approval step, or post this comment after "
                "the run reaches a terminal state."
            )
        return None
    unapproved = sorted(set(ids) - approved_ids(checkpoints))
    if unapproved:
        return (
            f"Refusing to post unapproved review findings: {unapproved}. "
            "A finding may be posted only after the adversarial pass accepts it and the user "
            "approves it, which records its id in a completed checkpoint's approved_finding_ids."
        )
    return None


def evaluate(
    tool_name: str,
    tool_input: dict[str, Any],
    workspace: Path,
    tool_use_id: str | None = None,
) -> str | None:
    try:
        sources = _v2_sources(workspace)
    except HookError as error:
        return str(error) if is_guarded(tool_name, tool_input) or marked_ids(extract_content(tool_input)) else None
    if sources is not None:
        return _evaluate_v2(tool_name, tool_input, workspace, sources, tool_use_id)
    return _evaluate_v1(tool_name, tool_input, workspace)


def _succeeded(payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Read the host's own report of what happened."""
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


def record(payload: dict[str, Any]) -> int:
    """Resolve the authorization this tool call consumed, and only that one."""
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0
    workspace = Path(payload.get("cwd") or Path.cwd())
    identifier = payload.get("tool_use_id")
    if not isinstance(identifier, str) or not identifier:
        identifier = call_fingerprint(tool_name, tool_input)
    try:
        path = find_active_checkpoint(workspace)
        if path is None:
            return 0
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        pending = checkpoint.get("pending_posts")
        if not isinstance(pending, dict) or identifier not in pending:
            return 0
        succeeded, detail = _succeeded(payload)
        record_outcome(path, identifier, succeeded, detail)
    except (OSError, json.JSONDecodeError, CheckpointError):
        return 0
    return 0


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
    if payload.get("hook_event_name") in {"PostToolUse", "PostToolUseFailure"}:
        return record(payload)
    workspace = Path(payload.get("cwd") or Path.cwd())
    try:
        reason = evaluate(tool_name, tool_input, workspace, payload.get("tool_use_id"))
    except OSError:
        return 0
    if reason is None:
        return 0
    print(f"Blocked by mcrt-review poster guard: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
