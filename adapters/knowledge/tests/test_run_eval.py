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
from datetime import date, timedelta
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


class ClockTest(unittest.TestCase):
    """The baseline must not decay just because time passed.

    The store's recency bonus is a function of a unit's age, so on the wall clock
    every number in the eval drifts a little each day against a fixture that never
    changes. This was not hypothetical: the day after the harness merged, the date
    rolled over and the ladder cost moved 20764 -> 20766 on an untouched tree.
    """

    def scores(self, today):
        store = RUNNER.STORE.KnowledgeStore(RUNNER.FIXTURE, today=today)
        hits, _ = store.find("payment gateway retry policy backoff", limit=RUNNER.FIND_LIMIT)
        return [(h.unit_id, h.anchor, h.score) for h in hits]

    def test_the_pin_is_load_bearing(self):
        """If the clock did not affect scoring, pinning it would prove nothing."""
        self.assertNotEqual(self.scores(RUNNER.EVAL_TODAY), self.scores(RUNNER.EVAL_TODAY + timedelta(days=400)))

    def test_the_eval_pins_the_clock_to_the_fixture_date(self):
        self.assertEqual(RUNNER.EVAL_TODAY, date(2026, 8, 30))
        dates = {unit.updated for unit in RUNNER.STORE.KnowledgeStore(RUNNER.FIXTURE).units.values()}
        self.assertEqual(dates, {RUNNER.EVAL_TODAY.isoformat()})

    def test_results_do_not_depend_on_when_the_eval_is_run(self):
        """The whole point: same fixture, same numbers, any day."""
        pinned = RUNNER.as_baseline(RUNNER.evaluate())
        baseline = json.loads((EVAL / "baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(pinned["total_ladder_tokens"], baseline["total_ladder_tokens"])
        self.assertEqual(pinned["margins"], baseline["margins"])
        self.assertEqual(pinned["per_question_rank"], baseline["per_question_rank"])


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

    def test_a_deleted_question_is_reported_as_removed_coverage(self):
        """Deleting the links-only question used to pass silently.

        Its baseline rank is legitimately ``None``, so the links-only exemption
        swallowed the fact that the question was gone: the aggregates did not
        move, the token total *fell*, and the run exited zero having lost its
        only link-traversal assertion.
        """
        with tempfile.TemporaryDirectory() as tmp:
            trimmed = Path(tmp) / "questions.tsv"
            rows = (EVAL / "questions.tsv").read_text(encoding="utf-8").splitlines(keepends=True)
            trimmed.write_text("".join(r for r in rows if not r.startswith("q08\t")), encoding="utf-8")
            thinner = RUNNER.evaluate(questions_path=trimmed)

        # Why this needed a check of its own: nothing else notices.
        self.assertEqual(thinner.rank_at_1, self.baseline["rank_at_1"])
        self.assertEqual(thinner.mrr, self.baseline["mrr"])
        self.assertLess(thinner.total_ladder_tokens, self.baseline["total_ladder_tokens"])
        self.assertNotIn("q08:links-only", thinner.assertions)

        problems = RUNNER.compare(thinner, self.baseline)
        self.assertTrue(any("q08" in p and "coverage was removed" in p for p in problems), problems)

    def test_the_links_only_exemption_survives_for_a_question_that_ran(self):
        """Guards the obvious wrong fix: deleting the exemption altogether.

        That would reintroduce the earlier bug, where a rank of ``None`` — which
        is correct behaviour for a links-only target — was read as the unit
        having dropped out of the results.
        """
        self.assertIsNone(self.baseline["per_question_rank"]["q08"])
        self.assertIsNone(self.result.per_question["q08"]["rank"])
        self.assertEqual([p for p in RUNNER.compare(self.result, self.baseline) if "q08" in p], [])

    def test_a_question_the_baseline_does_not_know_is_not_a_regression(self):
        ranks = {k: v for k, v in self.baseline["per_question_rank"].items() if k != "q05"}
        older = dict(self.baseline, per_question_rank=ranks)
        self.assertEqual(RUNNER.compare(self.result, older), [])

    def test_added_coverage_is_surfaced_even_though_it_passes(self):
        ranks = {k: v for k, v in self.baseline["per_question_rank"].items() if k != "q05"}
        older = dict(self.baseline, per_question_rank=ranks)
        rendered = RUNNER.render(self.result, older)
        self.assertIn("New questions since the baseline", rendered)
        self.assertIn("+ q05", rendered)


class CommandLineTest(unittest.TestCase):
    def test_a_clean_run_exits_zero(self):
        completed = subprocess.run(
            [sys.executable, str(EVAL / "run_eval.py")], capture_output=True, text=True
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("mean reciprocal rank", completed.stdout)

    def test_update_baseline_refuses_to_record_a_broken_invariant(self):
        """A baseline accepts metric movement. It must never accept a broken invariant."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "knowledge"
            shutil.copytree(ADAPTER, copy, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
            baseline = copy / "eval" / "baseline.json"
            before = baseline.read_bytes()

            # Sever the only edge that reaches the links-only target. The store
            # harvests links from the body as well as the frontmatter, so both
            # sites have to go.
            unit = copy / "eval" / "fixture" / "2-structure" / "domain-model.md"
            text = unit.read_text(encoding="utf-8")
            self.assertIn("[[2-structure/settlement-context]]", text)
            unit.write_text(
                text.replace("[[2-structure/settlement-context]]", "[[2-structure/conventions]]"),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(copy / "eval" / "run_eval.py"), "--update-baseline"],
                capture_output=True,
                text=True,
            )
            after = baseline.read_bytes()

        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("FAIL  q08:links-only", completed.stdout)
        self.assertIn("Refusing to write the baseline", completed.stderr)
        self.assertEqual(after, before, "a refused update must leave the baseline untouched")

    def test_update_baseline_still_writes_on_a_clean_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "knowledge"
            shutil.copytree(ADAPTER, copy, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
            baseline = copy / "eval" / "baseline.json"
            before = baseline.read_bytes()

            completed = subprocess.run(
                [sys.executable, str(copy / "eval" / "run_eval.py"), "--update-baseline"],
                capture_output=True,
                text=True,
            )
            after = baseline.read_bytes()

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Baseline written to", completed.stdout)
        # The fixture has not changed, so a re-record must reproduce it exactly.
        self.assertEqual(after, before)

    def test_a_deleted_question_fails_the_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "knowledge"
            shutil.copytree(ADAPTER, copy, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
            questions = copy / "eval" / "questions.tsv"
            rows = questions.read_text(encoding="utf-8").splitlines(keepends=True)
            questions.write_text("".join(r for r in rows if not r.startswith("q08\t")), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(copy / "eval" / "run_eval.py")], capture_output=True, text=True
            )

        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("coverage was removed", completed.stderr)

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
