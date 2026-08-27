from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ADAPTER = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mcrt_review_guards", ADAPTER / "mcrt_review_guards.py")
assert SPEC is not None and SPEC.loader is not None
GUARDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARDS)


def review_input(workspace: Path, **overrides):
    return {
        "workspace": str(workspace),
        "review_type": "task",
        "decision": "hold",
        **overrides,
    }


def phase_result(**overrides):
    return {
        "status": "complete",
        "model": "gpt-5.6-terra",
        "reasoning": "medium",
        "selected_skill": "review-task",
        "findings": [{"id": "finding-1", "verdict": "VERIFIED"}],
        "local_uncertainty": [],
        "recommended_next_action": "await approval",
        **overrides,
    }


def adversarial_result(**overrides):
    return {
        "status": "complete",
        "model": "gpt-5.6-sol",
        "reasoning": "high",
        "decisions": [{"id": "finding-1", "disposition": "accepted"}],
        "recommended_next_action": "await approval",
        **overrides,
    }


class ReviewGuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_routes_all_declared_review_types(self):
        for review_type, skill in GUARDS.REVIEW_SKILLS.items():
            self.assertEqual(GUARDS.validate_input(review_input(self.workspace, review_type=review_type))["selected_skill"], skill)

    def test_post_requires_explicit_finding_ids(self):
        with self.assertRaisesRegex(GUARDS.GuardError, "requires at least one"):
            GUARDS.validate_input(review_input(self.workspace, decision="post"))

    def test_quota_stops_at_exactly_fifty_percent(self):
        self.assertEqual(GUARDS.evaluate_quota({"kind": "remaining", "percent": 50})["reason"], "PAUSED_7D_QUOTA_50")
        self.assertEqual(GUARDS.evaluate_quota({"kind": "used", "percent": 50})["reason"], "PAUSED_7D_QUOTA_50")

    def test_ambiguous_quota_signal_pauses(self):
        self.assertEqual(GUARDS.evaluate_quota({"percent": 55})["reason"], "PAUSED_7D_QUOTA_SIGNAL_AMBIGUOUS")

    def test_checkpoint_requires_one_active_run_and_reconciles_approval(self):
        payload = GUARDS.validate_input(review_input(self.workspace))
        checkpoint = GUARDS.create_checkpoint(self.workspace, payload, GUARDS.evaluate_quota("unavailable"))
        with self.assertRaisesRegex(GUARDS.GuardError, "active"):
            GUARDS.create_checkpoint(self.workspace, payload, GUARDS.evaluate_quota("unavailable"))
        GUARDS.append_worker_result(checkpoint, phase_result())
        GUARDS.append_adversarial_result(checkpoint, adversarial_result())
        completed = GUARDS.complete_checkpoint(checkpoint, ["finding-1"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["approved_finding_ids"], ["finding-1"])

    def test_malformed_or_unverified_result_is_rejected(self):
        with self.assertRaisesRegex(GUARDS.GuardError, "missing fields"):
            GUARDS.validate_phase_result({}, "review-task")
        with self.assertRaisesRegex(GUARDS.GuardError, "must be VERIFIED"):
            GUARDS.validate_phase_result(phase_result(findings=[{"id": "finding-1", "verdict": "INCONCLUSIVE"}]), "review-task")

    def test_unknown_approval_is_rejected(self):
        with self.assertRaisesRegex(GUARDS.GuardError, "unknown"):
            GUARDS.reconcile_approval([{"id": "finding-1", "verdict": "VERIFIED"}], ["other"])

    def test_rejected_adversarial_finding_cannot_be_approved(self):
        payload = GUARDS.validate_input(review_input(self.workspace))
        checkpoint = GUARDS.create_checkpoint(self.workspace, payload, GUARDS.evaluate_quota("unavailable"))
        GUARDS.append_worker_result(checkpoint, phase_result())
        GUARDS.append_adversarial_result(checkpoint, adversarial_result(decisions=[{"id": "finding-1", "disposition": "rejected"}]))
        with self.assertRaisesRegex(GUARDS.GuardError, "not accepted"):
            GUARDS.complete_checkpoint(checkpoint, ["finding-1"])


if __name__ == "__main__":
    unittest.main()
