"""Durable, host-neutral checkpoint operations for the review harness."""

from __future__ import annotations

import json
import os
import platform
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
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


# A hook runs under a host timeout, so it can be killed between taking the lock
# and releasing it.  Locks therefore carry their owner and are recoverable when
# that owner is provably gone, while a live owner is always respected.
LOCK_MAX_AGE = timedelta(minutes=15)


def _lock_owner(lock: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _lock_is_held(owner: dict[str, Any] | None) -> bool:
    """Is the recorded owner still able to be holding this lock?

    An unreadable or ownerless lock is recoverable.  A lock owned by a process
    on this machine is respected while that process exists.  A lock from another
    machine cannot be probed, so it is respected until it ages out.
    """
    if owner is None:
        return False
    pid = owner.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if owner.get("host") != platform.node():
        created = owner.get("created_at")
        try:
            age = datetime.now(UTC) - datetime.fromisoformat(str(created))
        except (TypeError, ValueError):
            return False
        return age < LOCK_MAX_AGE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _acquire(lock: Path) -> None:
    for attempt in (1, 2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            owner = _lock_owner(lock)
            if attempt == 2 or _lock_is_held(owner):
                raise CheckpointError(f"checkpoint is locked by {owner or 'an unknown owner'}: {lock.stem}") from error
            lock.unlink(missing_ok=True)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "host": platform.node(), "created_at": _now()}, handle)
        return
    raise CheckpointError(f"checkpoint could not be locked: {lock.stem}")


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock = path.with_suffix(path.suffix + ".lock")
    _acquire(lock)
    try:
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
        "pending_posts": {},
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
        if checkpoint.get("status") in TERMINAL_STATUSES:
            raise CheckpointError("terminal checkpoint cannot be abandoned")
        checkpoint.update({"status": "abandoned", "abandoned_at": _now(), "abandon_reason": reason})
        _write(path, checkpoint)
        return checkpoint


def authorize(path: Path, event: dict[str, Any]) -> GateDecision:
    """Atomically consume finding ids before a host hook permits a post.

    The authorization is correlated with the host's tool call: the same
    ``tool_use_id`` must come back through ``record_outcome``, so an unrelated
    call cannot close the run and a failed post cannot be reported as a success.
    The checkpoint stays ``approved`` while calls are in flight, so a run with
    several approved findings can post all of them.
    """
    tool_use_id = event.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        raise CheckpointError("an MCRT authorization must carry the host tool_use_id")
    with _locked(path):
        checkpoint = _read(path)
        decision = evaluate_action(checkpoint, event)
        if not decision.allowed:
            return decision
        pending = checkpoint.setdefault("pending_posts", {})
        if not isinstance(pending, dict):
            raise CheckpointError("checkpoint pending_posts is malformed")
        if tool_use_id in pending:
            return GateDecision(False, f"MCRT tool call is already authorized: {tool_use_id}")
        checkpoint["attempted_finding_ids"] = sorted(set(checkpoint.get("attempted_finding_ids", [])) | set(decision.authorization_ids))
        pending[tool_use_id] = {"finding_ids": list(decision.authorization_ids), "authorized_at": _now()}
        checkpoint["last_authorized_at"] = _now()
        _write(path, checkpoint)
        return decision


def record_outcome(path: Path, tool_use_id: str, succeeded: bool, detail: str | None = None) -> dict[str, Any]:
    """Record the result of one authorized provider call.

    Only a pending authorization can be resolved, and only once.  A failure
    fails the run without reopening the findings it already consumed; the run
    completes only when every approved finding has a successful outcome and no
    call is still in flight.
    """
    if not isinstance(tool_use_id, str) or not tool_use_id:
        raise CheckpointError("tool_use_id must be non-empty")
    with _locked(path):
        checkpoint = _read(path)
        if checkpoint.get("status") in TERMINAL_STATUSES:
            raise CheckpointError(f"a {checkpoint.get('status')} checkpoint cannot record an outcome")
        pending = checkpoint.get("pending_posts")
        if not isinstance(pending, dict) or tool_use_id not in pending:
            raise CheckpointError(f"no pending MCRT authorization for tool call {tool_use_id}")
        authorization = pending.pop(tool_use_id)
        finding_ids = authorization.get("finding_ids", []) if isinstance(authorization, dict) else []
        outcomes = checkpoint.setdefault("post_outcomes", [])
        if not isinstance(outcomes, list):
            raise CheckpointError("checkpoint post_outcomes is malformed")
        outcomes.append({
            "tool_use_id": tool_use_id,
            "finding_ids": list(finding_ids) if isinstance(finding_ids, list) else [],
            "succeeded": bool(succeeded), "detail": detail, "recorded_at": _now(),
        })
        if not succeeded:
            checkpoint.update({"status": "failed", "failed_at": _now()})
        else:
            posted = {
                finding
                for outcome in outcomes
                if isinstance(outcome, dict) and outcome.get("succeeded")
                for finding in outcome.get("finding_ids", [])
            }
            approved = set(checkpoint.get("approved_finding_ids", []))
            if approved and approved <= posted and not pending:
                checkpoint.update({"status": "completed", "completed_at": _now()})
        _write(path, checkpoint)
        return checkpoint
