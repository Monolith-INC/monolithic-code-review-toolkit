#!/usr/bin/env python3.12
"""Deterministic guards for the Codex review-orchestrator adapter.

Semantic review judgement stays in isolated Codex workers. This module owns
only mechanical input validation, checkpoint state, approval reconciliation,
and authoritative quota interpretation.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.review_harness.contracts import REVIEW_SKILLS

PENDING_STATUSES = {"running", "pending_approval", "paused"}
PHASE_RESULT_REQUIRED = {
    "status", "model", "reasoning", "selected_skill", "findings",
    "local_uncertainty", "recommended_next_action",
}
VERDICTS = {"VERIFIED", "NOT VERIFIED", "INCONCLUSIVE"}
ADVERSARIAL_REQUIRED = {"status", "model", "reasoning", "decisions", "recommended_next_action"}
ADVERSARIAL_DISPOSITIONS = {"accepted", "rejected", "inconclusive"}


class GuardError(ValueError):
    """A deterministic contract violation that must block orchestration."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise GuardError(f"missing JSON file: {path}") from error
    except json.JSONDecodeError as error:
        raise GuardError(f"invalid JSON file: {path}: {error}") from error
    if not isinstance(value, dict):
        raise GuardError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_input(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "workspace", "review_type", "work_item_id", "pull_request_id", "lenses",
        "decision", "approved_finding_ids", "quota_signal",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise GuardError(f"unknown input fields: {sorted(unknown)}")
    workspace = payload.get("workspace")
    if not isinstance(workspace, str) or not Path(workspace).is_absolute():
        raise GuardError("workspace must be an absolute path")
    review_type = payload.get("review_type")
    if review_type not in REVIEW_SKILLS:
        raise GuardError(f"review_type must be one of: {sorted(REVIEW_SKILLS)}")
    decision = payload.get("decision", "hold")
    if decision not in {"hold", "post"}:
        raise GuardError("decision must be 'hold' or 'post'")
    approved = payload.get("approved_finding_ids", [])
    if not isinstance(approved, list) or not all(isinstance(item, str) and item for item in approved):
        raise GuardError("approved_finding_ids must be a list of non-empty strings")
    if decision == "post" and not approved:
        raise GuardError("post requires at least one approved finding id")
    lenses = payload.get("lenses", [])
    if not isinstance(lenses, list) or not set(lenses) <= {"typescript", "maintainability", "all"}:
        raise GuardError("lenses must contain only typescript, maintainability, or all")
    return {
        **payload,
        "decision": decision,
        "approved_finding_ids": approved,
        "lenses": lenses,
        "selected_skill": REVIEW_SKILLS[review_type],
    }


def evaluate_quota(signal: Any) -> dict[str, str]:
    if signal is None or signal == "unavailable":
        return {"state": "unavailable", "reason": "no authoritative seven-day quota signal"}
    if not isinstance(signal, dict) or set(signal) != {"kind", "percent"}:
        return {"state": "paused", "reason": "PAUSED_7D_QUOTA_SIGNAL_AMBIGUOUS"}
    kind, percent = signal["kind"], signal["percent"]
    if kind not in {"remaining", "used"} or not isinstance(percent, (int, float)) or not 0 <= percent <= 100:
        return {"state": "paused", "reason": "PAUSED_7D_QUOTA_SIGNAL_AMBIGUOUS"}
    if (kind == "remaining" and percent <= 50) or (kind == "used" and percent >= 50):
        return {"state": "paused", "reason": "PAUSED_7D_QUOTA_50"}
    return {"state": "available", "reason": f"authoritative {kind} signal permits work"}


def validate_phase_result(result: dict[str, Any], expected_skill: str) -> dict[str, Any]:
    missing = PHASE_RESULT_REQUIRED - set(result)
    if missing:
        raise GuardError(f"phase result missing fields: {sorted(missing)}")
    if result["status"] not in {"complete", "incomplete", "blocked"}:
        raise GuardError("phase result has invalid status")
    if result["selected_skill"] != expected_skill:
        raise GuardError("phase result selected_skill does not match the requested lifecycle review")
    if not isinstance(result["findings"], list) or not isinstance(result["local_uncertainty"], list):
        raise GuardError("findings and local_uncertainty must be lists")
    seen: set[str] = set()
    for finding in result["findings"]:
        if not isinstance(finding, dict) or not {"id", "verdict"} <= set(finding):
            raise GuardError("each finding requires id and verdict")
        if finding["id"] in seen:
            raise GuardError(f"duplicate finding id: {finding['id']}")
        seen.add(finding["id"])
        if finding["verdict"] not in VERDICTS:
            raise GuardError(f"invalid evidence verdict: {finding['verdict']}")
        if finding["verdict"] != "VERIFIED":
            raise GuardError("candidate findings must be VERIFIED before adversarial review")
    return result


def reconcile_approval(findings: list[dict[str, Any]], approved_ids: list[str]) -> list[dict[str, Any]]:
    indexed = {finding["id"]: finding for finding in findings}
    unknown = sorted(set(approved_ids) - set(indexed))
    if unknown:
        raise GuardError(f"approval names unknown finding ids: {unknown}")
    return [indexed[finding_id] for finding_id in approved_ids]


def validate_adversarial_result(result: dict[str, Any], candidate_ids: set[str]) -> dict[str, Any]:
    missing = ADVERSARIAL_REQUIRED - set(result)
    if missing:
        raise GuardError(f"adversarial result missing fields: {sorted(missing)}")
    if result["status"] not in {"complete", "blocked"}:
        raise GuardError("adversarial result has invalid status")
    decisions = result["decisions"]
    if not isinstance(decisions, list):
        raise GuardError("adversarial decisions must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, dict) or not {"id", "disposition"} <= set(decision):
            raise GuardError("each adversarial decision requires id and disposition")
        finding_id = decision["id"]
        if finding_id in indexed or finding_id not in candidate_ids:
            raise GuardError("adversarial decisions must identify each candidate exactly once")
        if decision["disposition"] not in ADVERSARIAL_DISPOSITIONS:
            raise GuardError("adversarial disposition is invalid")
        indexed[finding_id] = decision
    if result["status"] == "complete" and set(indexed) != candidate_ids:
        raise GuardError("a complete adversarial result must decide every candidate")
    return result


def checkpoint_dir(workspace: Path) -> Path:
    return workspace / ".monolithic-code-review" / "orchestrator"


def active_checkpoint(workspace: Path) -> Path | None:
    directory = checkpoint_dir(workspace)
    if not directory.is_dir():
        return None
    active = []
    for path in directory.glob("checkpoint-*.json"):
        checkpoint = _read_json(path)
        if checkpoint.get("status") in PENDING_STATUSES:
            active.append(path)
    if len(active) > 1:
        raise GuardError("more than one active review-orchestrator checkpoint exists")
    return active[0] if active else None


def create_checkpoint(workspace: Path, payload: dict[str, Any], quota: dict[str, str]) -> Path:
    if active_checkpoint(workspace) is not None:
        raise GuardError("an active review-orchestrator checkpoint already exists")
    run_id = uuid4().hex
    path = checkpoint_dir(workspace) / f"checkpoint-{run_id}.json"
    _write_json(path, {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "paused" if quota["state"] == "paused" else "running",
        "input": payload,
        "quota": quota,
        "worker_results": [],
        "approved_finding_ids": [],
    })
    return path


def append_worker_result(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    checkpoint = _read_json(path)
    if checkpoint.get("status") != "running":
        raise GuardError("cannot append a worker result to a terminal or paused checkpoint")
    result = validate_phase_result(result, checkpoint["input"]["selected_skill"])
    checkpoint["worker_results"].append(result)
    _write_json(path, checkpoint)
    return checkpoint


def append_adversarial_result(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    checkpoint = _read_json(path)
    if checkpoint.get("status") != "running" or not checkpoint["worker_results"]:
        raise GuardError("an adversarial result requires one completed lifecycle result")
    candidates = checkpoint["worker_results"][-1]["findings"]
    result = validate_adversarial_result(result, {finding["id"] for finding in candidates})
    checkpoint["adversarial_result"] = result
    checkpoint["status"] = "pending_approval" if result["status"] == "complete" else "running"
    _write_json(path, checkpoint)
    return checkpoint


def complete_checkpoint(path: Path, approved_ids: list[str]) -> dict[str, Any]:
    checkpoint = _read_json(path)
    if checkpoint.get("status") != "pending_approval":
        raise GuardError("only a pending-approval checkpoint can be completed")
    findings = checkpoint["worker_results"][-1]["findings"]
    accepted = {
        decision["id"] for decision in checkpoint.get("adversarial_result", {}).get("decisions", [])
        if decision["disposition"] == "accepted"
    }
    approved = reconcile_approval(findings, approved_ids)
    rejected = sorted({finding["id"] for finding in approved} - accepted)
    if rejected:
        raise GuardError(f"approval includes findings not accepted by the adversarial pass: {rejected}")
    checkpoint["approved_finding_ids"] = [item["id"] for item in approved]
    checkpoint["status"] = "completed"
    checkpoint["completed_at"] = datetime.now(UTC).isoformat()
    _write_json(path, checkpoint)
    return checkpoint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-input", "quota", "create-checkpoint"):
        item = commands.add_parser(name)
        item.add_argument("input", type=Path)
    append = commands.add_parser("append-result")
    append.add_argument("checkpoint", type=Path)
    append.add_argument("result", type=Path)
    adversarial = commands.add_parser("append-adversarial")
    adversarial.add_argument("checkpoint", type=Path)
    adversarial.add_argument("result", type=Path)
    complete = commands.add_parser("complete")
    complete.add_argument("checkpoint", type=Path)
    complete.add_argument("approved_ids", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate-input":
            output = validate_input(_read_json(args.input))
        elif args.command == "quota":
            output = evaluate_quota(_read_json(args.input).get("quota_signal"))
        elif args.command == "create-checkpoint":
            payload = validate_input(_read_json(args.input))
            quota = evaluate_quota(payload.get("quota_signal"))
            output = {"checkpoint": str(create_checkpoint(Path(payload["workspace"]), payload, quota)), "quota": quota}
        elif args.command == "append-result":
            output = append_worker_result(args.checkpoint, _read_json(args.result))
        elif args.command == "append-adversarial":
            output = append_adversarial_result(args.checkpoint, _read_json(args.result))
        else:
            approved = _read_json(args.approved_ids).get("approved_finding_ids")
            if not isinstance(approved, list) or not all(isinstance(item, str) for item in approved):
                raise GuardError("approved_ids JSON requires approved_finding_ids: string[]")
            output = complete_checkpoint(args.checkpoint, approved)
    except GuardError as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
