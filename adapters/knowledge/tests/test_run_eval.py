"""Tests for the eval harness itself.

A harness is only worth its numbers if it fails when it should. These cover the
comparison logic directly, plus one end-to-end run against the committed fixture,
so a broken runner cannot quietly report a green baseline.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1]
EVAL = ADAPTER / "eval"


def load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ADAPTER / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = load("eval/run_eval.py", "run_eval")


class FixtureTest(unittest.TestCase):
    def test_fixture_loads_every_unit(self):
        store = RUNNER.STORE.KnowledgeStore(RUNNER.FIXTURE)
        self.assertEqual(len(store.units), 23)

    def test_manifest_is_not_indexed_as_a_unit(self):
        store = RUNNER.STORE.KnowledgeStore(RUNNER.FIXTURE)
        self.assertNotIn("manifest", store.units)

    def test_every_question_names_a_unit_that_exists(self):
        store = RUNNER.STORE.KnowledgeStore(RUNNER.FIXTURE)
        for question in RUNNER.load_questions():
            self.assertIn(question.expect_unit, store.units, question.id)
            if question.distractor_unit:
                self.assertIn(question.distractor_unit, store.units, question.id)

    def test_every_expected_anchor_exists(self):
        store = RUNNER.STORE.KnowledgeStore(RUNNER.FIXTURE)
        for question in RUNNER.load_questions():
            if not question.expect_anchor:
                continue
            anchors = {s.anchor for s in store.unit(question.expect_unit).sections()}
            self.assertIn(question.expect_anchor, anchors, question.id)

    def test_the_planted_assumed_trap_is_the_only_assumed_unit(self):
        store = RUNNER.STORE.KnowledgeStore(RUNNER.FIXTURE)
        assumed = sorted(u.id for u in store.units.values() if u.provenance == "assumed")
        self.assertEqual(assumed, ["5-evolution/risks"])


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self.result = RUNNER.evaluate()

    def test_reports_every_question(self):
        self.assertEqual(len(self.result.per_question), 12)

    def test_all_assertions_pass_on_the_committed_fixture(self):
        self.assertTrue(all(self.result.assertions.values()), self.result.failures)
        self.assertEqual(self.result.failures, [])

    def test_links_only_question_is_excluded_from_ranking_metrics(self):
        # 12 questions, 11 scored: the links-only target is meant to be unfindable.
        self.assertIsNone(self.result.per_question["q08"]["rank"])
        self.assertLessEqual(self.result.rank_at_1, 1.0)
        self.assertAlmostEqual(self.result.rank_at_1, round(9 / 11, 4), places=3)

    def test_negative_margins_are_recorded_rather_than_hidden(self):
        # The fixture deliberately contains two questions the decoy wins.
        negative = [qid for qid, margin in self.result.margins.items() if margin < 0]
        self.assertEqual(sorted(negative), ["q01", "q02"])

    def test_matches_the_committed_baseline(self):
        baseline = json.loads((EVAL / "baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(RUNNER.compare(self.result, baseline), [])

    def test_is_reproducible(self):
        again = RUNNER.evaluate()
        self.assertEqual(RUNNER.as_baseline(again), RUNNER.as_baseline(self.result))


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.baseline = json.loads((EVAL / "baseline.json").read_text(encoding="utf-8"))
        self.result = RUNNER.evaluate()

    def test_a_rank_at_1_drop_is_a_regression(self):
        raised = dict(self.baseline, rank_at_1=1.0)
        self.assertTrue(any("rank@1 regressed" in p for p in RUNNER.compare(self.result, raised)))

    def test_a_per_question_rank_slip_is_a_regression(self):
        ranks = dict(self.baseline["per_question_rank"], q01=1)
        stricter = dict(self.baseline, per_question_rank=ranks)
        problems = RUNNER.compare(self.result, stricter)
        self.assertTrue(any("q01: rank worsened from 1 to 2" in p for p in problems))

    def test_a_narrowed_distractor_margin_is_a_regression(self):
        margins = dict(self.baseline["margins"], q03=99.0)
        stricter = dict(self.baseline, margins=margins)
        self.assertTrue(any("q03" in p and "narrowed" in p for p in RUNNER.compare(self.result, stricter)))

    def test_a_rising_token_cost_is_a_regression(self):
        cheaper = dict(self.baseline, total_ladder_tokens=1)
        self.assertTrue(any("token cost rose" in p for p in RUNNER.compare(self.result, cheaper)))

    def test_an_improvement_is_never_a_regression(self):
        pessimistic = dict(
            self.baseline,
            rank_at_1=0.0,
            rank_at_3=0.0,
            mrr=0.0,
            total_ladder_tokens=10**9,
            margins={qid: -999.0 for qid in self.baseline["margins"]},
            per_question_rank={qid: 99 for qid in self.baseline["per_question_rank"]},
        )
        self.assertEqual(RUNNER.compare(self.result, pessimistic), [])

    def test_a_failed_assertion_is_a_regression(self):
        broken = RUNNER.evaluate()
        broken.assertions["q09:assumed-trap"] = False
        self.assertIn("assertion failed: q09:assumed-trap", RUNNER.compare(broken, self.baseline))


class CommandLineTest(unittest.TestCase):
    def test_a_clean_run_exits_zero(self):
        completed = subprocess.run(
            [sys.executable, str(EVAL / "run_eval.py")], capture_output=True, text=True
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("mean reciprocal rank", completed.stdout)

    def test_a_perturbed_ranking_function_is_caught(self):
        """The end-to-end proof: break ranking, and the runner must notice."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "knowledge"
            shutil.copytree(ADAPTER, copy, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))

            store_source = copy / "knowledge_store.py"
            text = store_source.read_text(encoding="utf-8")
            original = "hits.sort(key=lambda hit: (-hit.score, hit.unit_id, hit.anchor))"
            self.assertIn(original, text)
            store_source.write_text(
                text.replace(original, "hits.sort(key=lambda hit: (hit.score, hit.unit_id, hit.anchor))"),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(copy / "eval" / "run_eval.py")], capture_output=True, text=True
            )
        self.assertEqual(completed.returncode, 1, "a broken ranking function must fail the eval")
        self.assertIn("rank@1 regressed", completed.stderr)


if __name__ == "__main__":
    unittest.main()
