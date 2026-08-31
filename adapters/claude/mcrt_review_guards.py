#!/usr/bin/env python3.12
"""Deterministic guards for the Claude review-orchestrator adapter.

Semantic review judgement stays in isolated Claude subagents. This module owns
only mechanical input validation, checkpoint state, the user-input round trip,
and approval reconciliation.

Ported from the Monolithic Code Review Toolkit Codex adapter
(adapters/codex/mcrt_review_guards.py). The Codex seven-day quota gate is
omitted: Claude Code exposes no authoritative equivalent signal.
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

from core.review_harness.contracts import (
    ContractError,
    PR_SCOPED_REVIEW_TYPES,
    REVIEW_SKILLS,
    binding_digest,
    validate_sources,
)
from core.review_harness.gate import ACTIVE_STATUSES

SKILL_NAMESPACE = "monolithic-code-review-toolkit"
PHASE_RESULT_REQUIRED = {
    "status", "agent", "selected_skill", "findings",
    "local_uncertainty", "recommended_next_action",
}
PHASE_STATUSES = {"complete", "incomplete", "blocked", "needs_input"}
VERDICTS = {"VERIFIED", "NOT VERIFIED", "INCONCLUSIVE"}
ADVERSARIAL_REQUIRED = {"status", "agent", "decisions", "recommended_next_action"}
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
        "decision", "approved_finding_ids",
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
    if decision == "post" and review_type not in PR_SCOPED_REVIEW_TYPES:
        raise GuardError(f"a {review_type} review has no pull request to post to")
    lenses = payload.get("lenses", [])
    if not isinstance(lenses, list) or not set(lenses) <= {"typescript", "maintainability", "all"}:
        raise GuardError("lenses must contain only typescript, maintainability, or all")
    skill = REVIEW_SKILLS[review_type]
    return {
        **payload,
        "decision": decision,
        "approved_finding_ids": approved,
        "lenses": lenses,
        "selected_skill": skill,
        "qualified_skill": f"{SKILL_NAMESPACE}:{skill}",
    }


def validate_phase_result(result: dict[str, Any], expected_skill: str) -> dict[str, Any]:
    missing = PHASE_RESULT_REQUIRED - set(result)
    if missing:
        raise GuardError(f"phase result missing fields: {sorted(missing)}")
    if result["status"] not in PHASE_STATUSES:
        raise GuardError("phase result has invalid status")
    if result["selected_skill"] != expected_skill:
        raise GuardError("phase result selected_skill does not match the requested lifecycle review")
    if not isinstance(result["findings"], list) or not isinstance(result["local_uncertainty"], list):
        raise GuardError("findings and local_uncertainty must be lists")
    if result["status"] == "needs_input":
        validate_input_request(result)
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


def validate_input_request(result: dict[str, Any]) -> list[dict[str, Any]]:
    questions = result.get("questions")
    if not isinstance(questions, list) or not questions:
        raise GuardError("a needs_input result requires a non-empty questions list")
    seen: set[str] = set()
    for question in questions:
        if not isinstance(question, dict) or not {"id", "question"} <= set(question):
            raise GuardError("each question requires id and question")
        if not isinstance(question["question"], str) or not question["question"].strip():
            raise GuardError("question text must be a non-empty string")
        if question["id"] in seen:
            raise GuardError(f"duplicate question id: {question['id']}")
        seen.add(question["id"])
        options = question.get("options", [])
        if not isinstance(options, list) or not all(isinstance(item, str) and item for item in options):
            raise GuardError("question options must be a list of non-empty strings")
    return questions


def reconcile_answers(questions: list[dict[str, Any]], answers: dict[str, Any]) -> dict[str, str]:
    asked = {question["id"] for question in questions}
    if not isinstance(answers, dict):
        raise GuardError("answers must be an object keyed by question id")
    unknown = sorted(set(answers) - asked)
    if unknown:
        raise GuardError(f"answers name unknown question ids: {unknown}")
    unanswered = sorted(asked - set(answers))
    if unanswered:
        raise GuardError(f"every question must be answered; missing: {unanswered}")
    for key, value in answers.items():
        if not isinstance(value, str) or not value.strip():
            raise GuardError(f"answer for {key} must be a non-empty string")
    return dict(answers)


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
    for path in sorted(directory.glob("checkpoint-*.json")):
        checkpoint = _read_json(path)
        if checkpoint.get("status") in ACTIVE_STATUSES:
            active.append(path)
    if len(active) > 1:
        raise GuardError("more than one active review-orchestrator checkpoint exists")
    return active[0] if active else None


def _v2_sources(workspace: Path) -> dict[str, Any] | None:
    """Return the validated v2 binding document, or None when the project is v1."""
    sources_path = workspace / ".monolithic-code-review" / "sources.json"
    if not sources_path.exists():
        return None
    try:
        raw_sources = json.loads(sources_path.read_text(encoding="utf-8"))
        if isinstance(raw_sources, dict) and raw_sources.get("version") != 2:
            return None
        return validate_sources(raw_sources)
    except (OSError, json.JSONDecodeError, ContractError) as error:
        raise GuardError(f"invalid v2 sources document: {sources_path}: {error}") from error


def _posting_identity(workspace: Path, payload: dict[str, Any], sources: dict[str, Any] | None) -> dict[str, str] | None:
    """Bind posting identity, but only for a review that targets a pull request.

    A task, story-preflight or feature review reports against a work item, so it
    has no repository/PR identity to bind and never reaches the posting gate.
    """
    if sources is None or payload.get("review_type") not in PR_SCOPED_REVIEW_TYPES:
        return None
    repository = f"{sources['scm'].get('owner', '')}/{sources['scm'].get('repo', '')}".strip("/")
    pull_request_id = str(payload.get("pull_request_id", ""))
    if not repository or not pull_request_id:
        raise GuardError("a PR-scoped v2 review requires scm owner/repo and pull_request_id identity")
    return {
        "workspace": str(workspace),
        "repository": repository,
        "pull_request_id": pull_request_id,
        "binding_digest": binding_digest(sources, prevalidated=True),
    }


def create_checkpoint(workspace: Path, payload: dict[str, Any]) -> Path:
    if active_checkpoint(workspace) is not None:
        raise GuardError("an active review-orchestrator checkpoint already exists")
    run_id = uuid4().hex
    path = checkpoint_dir(workspace) / f"checkpoint-{run_id}.json"
    sources = _v2_sources(workspace)
    identity = _posting_identity(workspace, payload, sources)
    checkpoint = {
        "schema_version": 2 if sources is not None else 1,
        "posting_enabled": identity is not None,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "input": payload,
        "worker_results": [],
        "input_exchanges": [],
        "approved_finding_ids": [],
    }
    if identity:
        checkpoint.update({
            "identity": identity, "attempted_finding_ids": [], "pending_posts": {}, "post_outcomes": [],
        })
    _write_json(path, checkpoint)
    return path


def append_worker_result(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    checkpoint = _read_json(path)
    if checkpoint.get("status") != "running":
        raise GuardError("cannot append a worker result to a terminal or paused checkpoint")
    result = validate_phase_result(result, checkpoint["input"]["selected_skill"])
    if result["status"] == "needs_input":
        raise GuardError("a needs_input result must be recorded with request-input, not append-result")
    checkpoint["worker_results"].append(result)
    _write_json(path, checkpoint)
    return checkpoint


def request_input(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    checkpoint = _read_json(path)
    if checkpoint.get("status") != "running":
        raise GuardError("only a running checkpoint can request user input")
    questions = validate_input_request(result)
    checkpoint["status"] = "pending_input"
    checkpoint["pending_input"] = {
        "agent": result.get("agent"),
        "questions": questions,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    _write_json(path, checkpoint)
    return checkpoint


def resolve_input(path: Path, answers: dict[str, Any]) -> dict[str, Any]:
    checkpoint = _read_json(path)
    if checkpoint.get("status") != "pending_input":
        raise GuardError("no pending input request to resolve")
    pending = checkpoint["pending_input"]
    resolved = reconcile_answers(pending["questions"], answers)
    checkpoint["input_exchanges"].append({
        "agent": pending.get("agent"),
        "questions": pending["questions"],
        "answers": resolved,
        "resolved_at": datetime.now(UTC).isoformat(),
    })
    checkpoint["status"] = "running"
    del checkpoint["pending_input"]
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
    postable = isinstance(checkpoint.get("identity"), dict) and checkpoint.get("posting_enabled", True)
    checkpoint["status"] = "approved" if postable else "completed"
    checkpoint["approved_at" if postable else "completed_at"] = datetime.now(UTC).isoformat()
    _write_json(path, checkpoint)
    return checkpoint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-input", "create-checkpoint"):
        item = commands.add_parser(name)
        item.add_argument("input", type=Path)
    active = commands.add_parser("active")
    active.add_argument("workspace", type=Path)
    for name in ("append-result", "append-adversarial", "request-input"):
        item = commands.add_parser(name)
        item.add_argument("checkpoint", type=Path)
        item.add_argument("result", type=Path)
    resolve = commands.add_parser("resolve-input")
    resolve.add_argument("checkpoint", type=Path)
    resolve.add_argument("answers", type=Path)
    complete = commands.add_parser("complete")
    complete.add_argument("checkpoint", type=Path)
    complete.add_argument("approved_ids", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate-input":
            output = validate_input(_read_json(args.input))
        elif args.command == "create-checkpoint":
            payload = validate_input(_read_json(args.input))
            output = {"checkpoint": str(create_checkpoint(Path(payload["workspace"]), payload))}
        elif args.command == "active":
            found = active_checkpoint(args.workspace.resolve())
            output = {"checkpoint": str(found) if found else None}
        elif args.command == "append-result":
            output = append_worker_result(args.checkpoint, _read_json(args.result))
        elif args.command == "request-input":
            output = request_input(args.checkpoint, _read_json(args.result))
        elif args.command == "resolve-input":
            answers = _read_json(args.answers).get("answers")
            output = resolve_input(args.checkpoint, answers)
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
