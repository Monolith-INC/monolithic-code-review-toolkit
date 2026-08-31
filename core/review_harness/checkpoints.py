"""Durable, host-neutral checkpoint operations for the review harness."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .gate import ACTIVE_STATUSES, TERMINAL_STATUSES, GateDecision, evaluate_action


class CheckpointError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def directory(workspace: Path) -> Path:
    return workspace / ".monolithic-code-review" / "orchestrator"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CheckpointError(f"invalid checkpoint: {path}") from error
    if not isinstance(value, dict):
        raise CheckpointError(f"checkpoint root is not an object: {path}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock = path.with_suffix(path.suffix + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise CheckpointError(f"checkpoint is locked: {path}") from error
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def find_active_checkpoint(workspace: Path) -> Path | None:
    """Return the one active checkpoint for a workspace, if there is one.

    Checkpoint filenames carry a random run id, so lexicographic order says
    nothing about recency and terminal checkpoints accumulate beside live ones.
    Selection is therefore by lifecycle status, and both ambiguous and malformed
    state raise rather than resolving to a guess.
    """
    folder = directory(workspace)
    if not folder.is_dir():
        return None
    active = [path for path in sorted(folder.glob("checkpoint-*.json")) if _read(path).get("status") in ACTIVE_STATUSES]
    if len(active) > 1:
        raise CheckpointError(f"more than one active review-harness checkpoint exists: {', '.join(path.name for path in active)}")
    return active[0] if active else None


def create(workspace: Path, identity: dict[str, str], approved_finding_ids: list[str] | None = None) -> Path:
    directory(workspace).mkdir(parents=True, exist_ok=True)
    if find_active_checkpoint(workspace) is not None:
        raise CheckpointError("an active review-harness checkpoint already exists")
    required = {"workspace", "repository", "pull_request_id", "binding_digest"}
    if set(identity) != required or any(not isinstance(value, str) or not value for value in identity.values()):
        raise CheckpointError("checkpoint identity must bind workspace, repository, pull_request_id, and binding_digest")
    run_id = uuid4().hex
    path = directory(workspace) / f"checkpoint-{run_id}.json"
    _write(path, {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": _now(),
        "status": "approved" if approved_finding_ids else "running",
        "identity": identity,
        "approved_finding_ids": approved_finding_ids or [],
        "attempted_finding_ids": [],
        "post_outcomes": [],
    })
    return path


def inspect(path: Path) -> dict[str, Any]:
    return _read(path)


def resume(path: Path) -> dict[str, Any]:
    with _locked(path):
        checkpoint = _read(path)
        if checkpoint.get("status") != "paused":
            raise CheckpointError("only a paused checkpoint may resume")
        checkpoint["status"] = "running"
        checkpoint["resumed_at"] = _now()
        _write(path, checkpoint)
        return checkpoint


def abandon(path: Path, reason: str) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason.strip():
        raise CheckpointError("abandon reason must be non-empty")
    with _locked(path):
        checkpoint = _read(path)
        if checkpoint.get("status") in {"completed", "failed", "abandoned"}:
            raise CheckpointError("terminal checkpoint cannot be abandoned")
        checkpoint.update({"status": "abandoned", "abandoned_at": _now(), "abandon_reason": reason})
        _write(path, checkpoint)
        return checkpoint


def authorize(path: Path, event: dict[str, Any]) -> GateDecision:
    """Atomically consume finding ids before a host hook permits a post."""
    with _locked(path):
        checkpoint = _read(path)
        decision = evaluate_action(checkpoint, event)
        if not decision.allowed:
            return decision
        checkpoint["attempted_finding_ids"] = sorted(set(checkpoint.get("attempted_finding_ids", [])) | set(decision.authorization_ids))
        checkpoint["status"] = "attempting"
        checkpoint["last_authorized_at"] = _now()
        _write(path, checkpoint)
        return decision


def record_outcome(path: Path, tool_use_id: str, succeeded: bool, detail: str | None = None) -> dict[str, Any]:
    if not isinstance(tool_use_id, str) or not tool_use_id:
        raise CheckpointError("tool_use_id must be non-empty")
    with _locked(path):
        checkpoint = _read(path)
        checkpoint.setdefault("post_outcomes", []).append({
            "tool_use_id": tool_use_id, "succeeded": bool(succeeded), "detail": detail, "recorded_at": _now(),
        })
        checkpoint["status"] = "completed" if succeeded else "failed"
        _write(path, checkpoint)
        return checkpoint
