#!/usr/bin/env python3.12
"""Codex PreToolUse/PostToolUse translation for the core MCRT action gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.review_harness.checkpoints import CheckpointError, authorize, record_outcome
from core.review_harness.contracts import ContractError, binding_digest, validate_sources


def _sources(workspace: Path) -> dict[str, Any] | None:
    path = workspace / ".monolithic-code-review" / "sources.json"
    try:
        return validate_sources(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ContractError):
        return None


def _checkpoint(workspace: Path) -> Path | None:
    candidates = sorted((workspace / ".monolithic-code-review" / "orchestrator").glob("checkpoint-*.json"))
    return candidates[-1] if candidates else None


def _match_write(sources: dict[str, Any], tool_name: str) -> bool:
    for binding in sources["scm"].get("capabilities", {}).values():
        if binding.get("access") == "write" and binding.get("kind") == "mcp_tool":
            if tool_name == f"mcp__{binding['server']}__{binding['tool']}":
                return True
    return tool_name == "Bash"  # Bash is fail-closed for an MCRT-marked write.


def evaluate(payload: dict[str, Any]) -> str | None:
    workspace = Path(payload.get("cwd", ""))
    if not workspace.is_absolute():
        return None
    sources = _sources(workspace)
    tool_input = payload.get("tool_input")
    if sources is None or not isinstance(tool_input, dict) or not _match_write(sources, str(payload.get("tool_name", ""))):
        return None
    ids = tool_input.get("mcrt_finding_ids")
    if not isinstance(ids, list) or not ids:
        return None
    path = _checkpoint(workspace)
    if path is None:
        return "MCRT-marked action has no approval checkpoint"
    repository = f"{sources['scm'].get('owner', '')}/{sources['scm'].get('repo', '')}".strip("/")
    event = {
        "mcrt": True, "role": "poster" if payload.get("agent_type") == "mcrt_review_poster" else None,
        "finding_ids": ids, "workspace": str(workspace), "repository": repository,
        "pull_request_id": str(tool_input.get("pull_request_id", tool_input.get("pr", ""))),
        "binding_digest": binding_digest(sources),
    }
    try:
        decision = authorize(path, event)
    except CheckpointError as error:
        return str(error)
    return None if decision.allowed else decision.reason


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("hook_event_name") == "PostToolUse":
        workspace = Path(payload.get("cwd", ""))
        path = _checkpoint(workspace) if workspace.is_absolute() else None
        tool_use_id = payload.get("tool_use_id")
        if path and isinstance(tool_use_id, str):
            try:
                checkpoint = json.loads(path.read_text(encoding="utf-8"))
                if checkpoint.get("status") == "attempting":
                    record_outcome(path, tool_use_id, True)
            except (OSError, json.JSONDecodeError, CheckpointError):
                return 2
        return 0
    if payload.get("hook_event_name") != "PreToolUse":
        return 0
    reason = evaluate(payload)
    if reason is None:
        return 0
    print(f"Blocked by MCRT deterministic action gate: {reason}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
