from __future__ import annotations

import importlib.util
import json
import tempfile
import sys
import unittest
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ADAPTER / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

GUARDS = load("mcrt_review_guards.py", "mcrt_review_guards")


def write_v2_sources(workspace: Path) -> None:
    directory = workspace / ".monolithic-code-review"
    directory.mkdir(parents=True, exist_ok=True)
    value = {
        "version": 2,
        "scm": {"owner": "Monolith-INC", "repo": "mcrt", "capabilities": {}, "unsupported": []},
        "tracker": {"capabilities": {}, "unsupported": []},
    }
    (directory / "sources.json").write_text(json.dumps(value), encoding="utf-8")


def review_input(workspace: Path, **overrides):
    return {"workspace": str(workspace), "review_type": "task", "decision": "hold", **overrides}


def phase_result(**overrides):
    return {
        "status": "complete",
        "agent": "mcrt-review-validator",
        "selected_skill": "review-task",
        "findings": [{"id": "finding-1", "verdict": "VERIFIED"}],
        "local_uncertainty": [],
        "recommended_next_action": "await approval",
        **overrides,
    }


def adversarial_result(**overrides):
    return {
        "status": "complete",
        "agent": "mcrt-review-adversarial",
        "decisions": [{"id": "finding-1", "disposition": "accepted"}],
        "recommended_next_action": "await approval",
        **overrides,
    }


class InputValidationTest(unittest.TestCase):
    def test_resolves_and_namespaces_the_lifecycle_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = GUARDS.validate_input(review_input(Path(tmp), review_type="story-postflight"))
        self.assertEqual(payload["selected_skill"], "review-story-postflight")
        self.assertEqual(
            payload["qualified_skill"],
            "monolithic-code-review-toolkit:review-story-postflight",
        )

    def test_rejects_relative_workspace(self):
        with self.assertRaises(GUARDS.GuardError):
            GUARDS.validate_input({"workspace": "relative/path", "review_type": "task"})

    def test_rejects_unknown_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.validate_input(review_input(Path(tmp), quota_signal={"kind": "remaining"}))

    def test_post_requires_approved_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.validate_input(review_input(Path(tmp), decision="post"))

    def test_rejects_unknown_lens(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.validate_input(review_input(Path(tmp), lenses=["python"]))


class PhaseResultTest(unittest.TestCase):
    def test_rejects_unverified_candidate(self):
        result = phase_result(findings=[{"id": "finding-1", "verdict": "INCONCLUSIVE"}])
        with self.assertRaises(GUARDS.GuardError):
            GUARDS.validate_phase_result(result, "review-task")

    def test_rejects_duplicate_finding_id(self):
        result = phase_result(findings=[
            {"id": "finding-1", "verdict": "VERIFIED"},
            {"id": "finding-1", "verdict": "VERIFIED"},
        ])
        with self.assertRaises(GUARDS.GuardError):
            GUARDS.validate_phase_result(result, "review-task")

    def test_rejects_skill_mismatch(self):
        with self.assertRaises(GUARDS.GuardError):
            GUARDS.validate_phase_result(phase_result(), "review-feature")


class InputRoundTripTest(unittest.TestCase):
    def _running_checkpoint(self, tmp: str) -> Path:
        workspace = Path(tmp)
        payload = GUARDS.validate_input(review_input(workspace))
        return GUARDS.create_checkpoint(workspace, payload)

    def test_request_then_resolve_returns_to_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._running_checkpoint(tmp)
            request = phase_result(status="needs_input", findings=[], questions=[
                {"id": "q1", "question": "Which work item is authoritative?", "options": ["7311", "7384"]},
            ])
            checkpoint = GUARDS.request_input(path, request)
            self.assertEqual(checkpoint["status"], "pending_input")
            self.assertEqual(GUARDS.active_checkpoint(Path(tmp)), path)

            checkpoint = GUARDS.resolve_input(path, {"q1": "7311"})
            self.assertEqual(checkpoint["status"], "running")
            self.assertNotIn("pending_input", checkpoint)
            self.assertEqual(checkpoint["input_exchanges"][0]["answers"], {"q1": "7311"})

    def test_needs_input_cannot_be_appended_as_a_worker_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._running_checkpoint(tmp)
            request = phase_result(status="needs_input", findings=[], questions=[
                {"id": "q1", "question": "Which work item?"},
            ])
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.append_worker_result(path, request)

    def test_partial_answers_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._running_checkpoint(tmp)
            GUARDS.request_input(path, phase_result(status="needs_input", findings=[], questions=[
                {"id": "q1", "question": "First?"},
                {"id": "q2", "question": "Second?"},
            ]))
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.resolve_input(path, {"q1": "yes"})

    def test_unknown_answer_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._running_checkpoint(tmp)
            GUARDS.request_input(path, phase_result(status="needs_input", findings=[], questions=[
                {"id": "q1", "question": "First?"},
            ]))
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.resolve_input(path, {"q1": "yes", "q9": "stray"})

    def test_needs_input_without_questions_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._running_checkpoint(tmp)
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.request_input(path, phase_result(status="needs_input", findings=[], questions=[]))

    def test_resolve_without_pending_request_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._running_checkpoint(tmp)
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.resolve_input(path, {"q1": "yes"})


class ApprovalTest(unittest.TestCase):
    def _to_pending_approval(self, tmp: str, adversarial=None) -> Path:
        workspace = Path(tmp)
        payload = GUARDS.validate_input(review_input(workspace))
        path = GUARDS.create_checkpoint(workspace, payload)
        GUARDS.append_worker_result(path, phase_result())
        GUARDS.append_adversarial_result(path, adversarial or adversarial_result())
        return path

    def test_completes_with_an_accepted_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._to_pending_approval(tmp)
            checkpoint = GUARDS.complete_checkpoint(path, ["finding-1"])
        self.assertEqual(checkpoint["status"], "completed")
        self.assertEqual(checkpoint["approved_finding_ids"], ["finding-1"])

    def test_v2_approval_binds_repository_identity_for_the_poster_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            write_v2_sources(workspace)
            payload = GUARDS.validate_input(review_input(workspace, pull_request_id="42"))
            path = GUARDS.create_checkpoint(workspace, payload)
            GUARDS.append_worker_result(path, phase_result())
            GUARDS.append_adversarial_result(path, adversarial_result())
            checkpoint = GUARDS.complete_checkpoint(path, ["finding-1"])
        self.assertEqual(checkpoint["schema_version"], 2)
        self.assertEqual(checkpoint["status"], "approved")
        self.assertEqual(checkpoint["identity"]["repository"], "Monolith-INC/mcrt")
        self.assertEqual(checkpoint["identity"]["pull_request_id"], "42")

    def test_cannot_approve_a_rejected_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._to_pending_approval(tmp, adversarial_result(
                decisions=[{"id": "finding-1", "disposition": "rejected"}],
            ))
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.complete_checkpoint(path, ["finding-1"])

    def test_cannot_approve_an_unknown_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._to_pending_approval(tmp)
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.complete_checkpoint(path, ["finding-9"])

    def test_adversarial_must_decide_every_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = GUARDS.validate_input(review_input(workspace))
            path = GUARDS.create_checkpoint(workspace, payload)
            GUARDS.append_worker_result(path, phase_result(findings=[
                {"id": "finding-1", "verdict": "VERIFIED"},
                {"id": "finding-2", "verdict": "VERIFIED"},
            ]))
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.append_adversarial_result(path, adversarial_result())

    def test_second_concurrent_run_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = GUARDS.validate_input(review_input(workspace))
            GUARDS.create_checkpoint(workspace, payload)
            with self.assertRaises(GUARDS.GuardError):
                GUARDS.create_checkpoint(workspace, payload)


if __name__ == "__main__":
    unittest.main()
