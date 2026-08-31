from __future__ import annotations

import importlib.util
import json
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


def write_v2_sources(workspace: Path) -> None:
    directory = workspace / ".monolithic-code-review"
    directory.mkdir(parents=True, exist_ok=True)
    value = {
        "version": 2,
        "scm": {"owner": "Monolith-INC", "repo": "mcrt", "capabilities": {}, "unsupported": []},
        "tracker": {"capabilities": {}, "unsupported": []},
    }
    (directory / "sources.json").write_text(json.dumps(value), encoding="utf-8")


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

    def test_v2_approval_binds_repository_identity_for_the_post_hook(self):
        write_v2_sources(self.workspace)
        payload = GUARDS.validate_input(review_input(self.workspace, pull_request_id="42"))
        checkpoint = GUARDS.create_checkpoint(
            self.workspace, payload, GUARDS.evaluate_quota("unavailable"),
        )
        GUARDS.append_worker_result(checkpoint, phase_result())
        GUARDS.append_adversarial_result(checkpoint, adversarial_result())
        completed = GUARDS.complete_checkpoint(checkpoint, ["finding-1"])
        self.assertEqual(completed["schema_version"], 2)
        self.assertEqual(completed["status"], "approved")
        self.assertEqual(completed["identity"]["repository"], "Monolith-INC/mcrt")
        self.assertEqual(completed["identity"]["pull_request_id"], "42")

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


class PostingEligibilityTest(unittest.TestCase):
    """A review that has no pull request must not be treated as postable."""

    NON_PR_TYPES = ("task", "story-preflight", "feature")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        write_v2_sources(self.workspace)

    def quota(self):
        return GUARDS.evaluate_quota("unavailable")

    def run_to_approval(self, review_type: str, **overrides):
        payload = GUARDS.validate_input(review_input(self.workspace, review_type=review_type, **overrides))
        checkpoint = GUARDS.create_checkpoint(self.workspace, payload, self.quota())
        GUARDS.append_worker_result(checkpoint, phase_result(selected_skill=GUARDS.REVIEW_SKILLS[review_type]))
        GUARDS.append_adversarial_result(checkpoint, adversarial_result())
        return GUARDS.complete_checkpoint(checkpoint, ["finding-1"])

    def test_a_non_pr_review_needs_no_pull_request_id(self):
        for review_type in self.NON_PR_TYPES:
            with self.subTest(review_type=review_type):
                payload = GUARDS.validate_input(review_input(self.workspace, review_type=review_type, work_item_id="WI-1"))
                path = GUARDS.create_checkpoint(self.workspace, payload, self.quota())
                checkpoint = json.loads(path.read_text(encoding="utf-8"))
                self.assertFalse(checkpoint["posting_enabled"])
                self.assertNotIn("identity", checkpoint)
                # Close the run so the next review type gets a fresh workspace slot.
                path.write_text(json.dumps(dict(checkpoint, status="abandoned")), encoding="utf-8")

    def test_a_non_pr_review_completes_without_becoming_postable(self):
        for review_type in self.NON_PR_TYPES:
            with self.subTest(review_type=review_type):
                temp = tempfile.TemporaryDirectory()
                self.addCleanup(temp.cleanup)
                self.workspace = Path(temp.name) / "workspace"
                self.workspace.mkdir()
                write_v2_sources(self.workspace)
                checkpoint = self.run_to_approval(review_type, work_item_id="WI-1")
                self.assertEqual(checkpoint["status"], "completed")
                self.assertFalse(checkpoint["posting_enabled"])

    def test_a_non_pr_review_cannot_request_a_post(self):
        for review_type in self.NON_PR_TYPES:
            with self.subTest(review_type=review_type):
                with self.assertRaisesRegex(GUARDS.GuardError, "post"):
                    GUARDS.validate_input(review_input(
                        self.workspace, review_type=review_type, decision="post",
                        approved_finding_ids=["finding-1"],
                    ))

    def test_a_pr_scoped_review_binds_posting_identity(self):
        checkpoint = self.run_to_approval("story-postflight", pull_request_id="42")
        self.assertEqual(checkpoint["status"], "approved")
        self.assertTrue(checkpoint["posting_enabled"])
        self.assertEqual(checkpoint["identity"]["repository"], "Monolith-INC/mcrt")
        self.assertEqual(checkpoint["identity"]["pull_request_id"], "42")

    def test_a_pr_scoped_review_still_requires_its_pull_request_id(self):
        payload = GUARDS.validate_input(review_input(self.workspace, review_type="story-postflight"))
        with self.assertRaisesRegex(GUARDS.GuardError, "pull_request_id"):
            GUARDS.create_checkpoint(self.workspace, payload, self.quota())

    def test_an_attempting_checkpoint_is_not_active(self):
        payload = GUARDS.validate_input(review_input(self.workspace, review_type="task", work_item_id="WI-1"))
        path = GUARDS.create_checkpoint(self.workspace, payload, self.quota())
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(dict(checkpoint, status="attempting")), encoding="utf-8")
        self.assertIsNone(GUARDS.active_checkpoint(self.workspace))


if __name__ == "__main__":
    unittest.main()
