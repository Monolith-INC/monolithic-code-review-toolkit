#!/usr/bin/env python3.12
"""Tier 1 of the knowledge retrieval eval: deterministic, offline, no model.

Measures what a machine can measure honestly:

  * **rank@1 / rank@3** — where the correct unit lands in `find`, deduplicated to
    units. Not "hit@1" — picking a unit from the catalog is a judgement, and this
    harness makes none. See `model_eval.md` for the tier that does.
  * **Ladder token cost** — tokens a fixed catalog → find → fetch policy spends
    before the correct unit's content is in hand. Bad ranking costs real tokens
    here, because the policy fetches wrong units on the way down.
  * **Distractor margin** — score gap between the correct unit and its planted
    near-miss. A negative margin means the decoy wins, which is the mechanical
    shadow of an agent citing the wrong unit. A shadow, not the thing itself.

Plus four pass/fail assertions that are not scored: the links-only target is
unreachable by search, the assumed trap is labelled uncitable, the oversized unit
truncates with a handle that actually advances, and ordering is reproducible.

    python3.12 adapters/knowledge/eval/run_eval.py [--update-baseline] [--json]

Exits non-zero when a measurement regresses against `baseline.json`, or when any
assertion fails.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
ADAPTER_DIR = EVAL_DIR.parent
FIXTURE = EVAL_DIR / "fixture"
QUESTIONS = EVAL_DIR / "questions.tsv"
BASELINE = EVAL_DIR / "baseline.json"

#: The budget the scripted policy fetches under. Matches the server's own default
#: so the token numbers mean the same thing in both places.
FETCH_BUDGET = 2000
FIND_LIMIT = 8

#: How far a measurement may drift before the run fails. Ranking is deterministic,
#: so these are tight on purpose — they exist for float noise, not for slippage.
RANK_TOLERANCE = 0.0
TOKEN_TOLERANCE = 0.02
MARGIN_TOLERANCE = 0.05


def _load_store_module():
    """Import the store directly, so this runs wherever the store tests run."""
    spec = importlib.util.spec_from_file_location(
        "knowledge_store", ADAPTER_DIR / "knowledge_store.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["knowledge_store"] = module
    spec.loader.exec_module(module)
    return module


STORE = _load_store_module()


@dataclass
class Question:
    id: str
    question: str
    expect_unit: str
    expect_anchor: str
    kind: str
    distractor_unit: str
    notes: str


@dataclass
class Result:
    rank_at_1: float = 0.0
    rank_at_3: float = 0.0
    mrr: float = 0.0
    total_ladder_tokens: int = 0
    per_question: dict[str, Any] = field(default_factory=dict)
    margins: dict[str, float] = field(default_factory=dict)
    assertions: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


def load_questions(path: Path = QUESTIONS) -> list[Question]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    for row in csv.DictReader(lines, delimiter="\t"):
        rows.append(
            Question(
                id=row["id"],
                question=row["question"],
                expect_unit=row["expect_unit"],
                expect_anchor=(row.get("expect_anchor") or "").strip(),
                kind=row["kind"],
                distractor_unit=(row.get("distractor_unit") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            )
        )
    return rows


def ranked_units(hits) -> list[str]:
    """Collapse section-grained hits to units, keeping first appearance.

    `find` ranks sections, but the question a reader asks is which *unit* to open,
    so the metric has to be unit-grained or it flatters itself.
    """
    seen: dict[str, None] = {}
    for hit in hits:
        seen.setdefault(hit.unit_id, None)
    return list(seen)


def ladder_tokens(store, question: Question, hits) -> int:
    """Tokens a catalog → find → fetch policy spends reaching the correct unit.

    Wrong units ranked above the right one are fetched on the way down and charged
    for, which is what couples this metric to ranking quality.
    """
    catalog_rows = store.catalog()
    catalog_text = "\n".join(
        "\t".join(str(row[column]) for column in STORE.CATALOG_COLUMNS) for row in catalog_rows
    )
    total = STORE.estimate_tokens(catalog_text)

    find_text = "\n".join(
        f"{hit.unit_id}#{hit.anchor} {hit.score} {','.join(hit.matched_terms)} {hit.snippet}"
        for hit in hits
    )
    total += STORE.estimate_tokens(find_text)

    for unit_id in ranked_units(hits):
        try:
            fetched = store.fetch(unit_id, max_tokens=FETCH_BUDGET)
        except STORE.StoreError:
            continue
        total += STORE.estimate_tokens(fetched["content"])
        if unit_id == question.expect_unit:
            return total

    # Never reached by search. The policy falls back to opening the unit directly,
    # which is what a reader would do once links pointed them at it.
    try:
        fetched = store.fetch(question.expect_unit, max_tokens=FETCH_BUDGET)
        total += STORE.estimate_tokens(fetched["content"])
    except STORE.StoreError:
        pass
    return total


def check_links_only(store, question: Question, hits, result: Result) -> None:
    """The target must be unreachable by search and reachable by traversal."""
    reachable_by_search = question.expect_unit in ranked_units(hits)
    edges = store.links(question.distractor_unit, direction="out")
    reachable_by_links = question.expect_unit in edges.get("out", [])

    ok = (not reachable_by_search) and reachable_by_links
    result.assertions[f"{question.id}:links-only"] = ok
    if not ok:
        result.failures.append(
            f"{question.id}: expected {question.expect_unit} to be reachable only via links "
            f"(search={reachable_by_search}, links={reachable_by_links})"
        )


def check_assumed_trap(store, question: Question, hits, result: Result) -> None:
    """The best topical match is inference and must announce itself as such."""
    units = ranked_units(hits)
    top_is_target = bool(units) and units[0] == question.expect_unit
    provenance = store.unit(question.expect_unit).provenance

    ok = top_is_target and provenance == "assumed"
    result.assertions[f"{question.id}:assumed-trap"] = ok
    if not ok:
        result.failures.append(
            f"{question.id}: expected {question.expect_unit} to top the results with "
            f"provenance 'assumed' (top={units[0] if units else None}, provenance={provenance})"
        )


def check_truncation(store, question: Question, result: Result) -> None:
    """Over-budget content must truncate and its handle must actually advance."""
    first = store.fetch(question.expect_unit, max_tokens=120)
    ok = bool(first["truncated"]) and first["continuation"] is not None
    if ok:
        handle = first["continuation"]
        second = store.fetch(
            question.expect_unit, start_line=handle["start_line"], max_tokens=120
        )
        ok = bool(second["content"]) and second["content"] != first["content"]

    result.assertions[f"{question.id}:truncation-advances"] = ok
    if not ok:
        result.failures.append(
            f"{question.id}: expected {question.expect_unit} to truncate and continue to new content"
        )


def check_determinism(store, questions: list[Question], result: Result) -> None:
    """Ordering is a documented contract; a harness should hold it to that."""
    ok = True
    for question in questions:
        first, _ = store.find(question.question, limit=FIND_LIMIT)
        second, _ = store.find(question.question, limit=FIND_LIMIT)
        if [(h.unit_id, h.anchor, h.score) for h in first] != [
            (h.unit_id, h.anchor, h.score) for h in second
        ]:
            ok = False
            result.failures.append(f"{question.id}: find ordering was not reproducible")
    result.assertions["ordering-deterministic"] = ok


def evaluate(fixture: Path = FIXTURE, questions_path: Path = QUESTIONS) -> Result:
    store = STORE.KnowledgeStore(fixture)
    questions = load_questions(questions_path)
    result = Result()

    at_1 = at_3 = 0
    reciprocal = 0.0
    for question in questions:
        hits, _ = store.find(question.question, limit=FIND_LIMIT)
        units = ranked_units(hits)
        rank = units.index(question.expect_unit) + 1 if question.expect_unit in units else None

        tokens = ladder_tokens(store, question, hits)
        result.total_ladder_tokens += tokens

        # A links-only target is *supposed* to be unfindable, so counting it as a
        # ranking miss would punish the store for behaving correctly.
        if question.kind != "links-only":
            if rank == 1:
                at_1 += 1
            if rank is not None and rank <= 3:
                at_3 += 1
            # Reciprocal rank moves when a question slips from 2 to 3, which
            # rank@1 and rank@3 both sleep through.
            reciprocal += 1 / rank if rank else 0.0

        result.per_question[question.id] = {
            "kind": question.kind,
            "expect_unit": question.expect_unit,
            "rank": rank,
            "top_unit": units[0] if units else None,
            "ladder_tokens": tokens,
        }

        if question.kind == "distractor":
            correct = next((h.score for h in hits if h.unit_id == question.expect_unit), 0.0)
            decoy = next((h.score for h in hits if h.unit_id == question.distractor_unit), 0.0)
            result.margins[question.id] = round(correct - decoy, 4)
            result.per_question[question.id]["distractor_unit"] = question.distractor_unit
        elif question.kind == "links-only":
            check_links_only(store, question, hits, result)
        elif question.kind == "assumed-trap":
            check_assumed_trap(store, question, hits, result)
        elif question.kind == "truncated":
            check_truncation(store, question, result)

    scored = [q for q in questions if q.kind != "links-only"]
    result.rank_at_1 = round(at_1 / len(scored), 4)
    result.rank_at_3 = round(at_3 / len(scored), 4)
    result.mrr = round(reciprocal / len(scored), 4)

    check_determinism(store, questions, result)
    return result


def compare(result: Result, baseline: dict[str, Any]) -> list[str]:
    """Regressions only. An improvement is never a failure — record it instead."""
    problems: list[str] = []

    if result.rank_at_1 < baseline["rank_at_1"] - RANK_TOLERANCE:
        problems.append(
            f"rank@1 regressed: {result.rank_at_1} < {baseline['rank_at_1']}"
        )
    if result.rank_at_3 < baseline["rank_at_3"] - RANK_TOLERANCE:
        problems.append(
            f"rank@3 regressed: {result.rank_at_3} < {baseline['rank_at_3']}"
        )

    if result.mrr < baseline["mrr"] - RANK_TOLERANCE:
        problems.append(f"mean reciprocal rank regressed: {result.mrr} < {baseline['mrr']}")

    # The aggregate metrics are coarse: with a dozen questions, a real ranking
    # change can leave rank@1 untouched. Per-question ranks are what actually
    # catch that, so they are compared individually.
    for qid, recorded in baseline["per_question_rank"].items():
        entry = result.per_question.get(qid, {})
        # A links-only target has no rank by design; comparing it would flag the
        # store as regressing for behaving exactly as intended.
        if entry.get("kind") == "links-only" or recorded is None:
            continue
        current = entry.get("rank")
        if current is None:
            problems.append(f"{qid}: correct unit dropped out of the results entirely")
        elif current > recorded:
            problems.append(f"{qid}: rank worsened from {recorded} to {current}")

    ceiling = baseline["total_ladder_tokens"] * (1 + TOKEN_TOLERANCE)
    if result.total_ladder_tokens > ceiling:
        problems.append(
            f"ladder token cost rose: {result.total_ladder_tokens} > {ceiling:.0f} "
            f"(baseline {baseline['total_ladder_tokens']})"
        )

    for qid, recorded in baseline["margins"].items():
        current = result.margins.get(qid)
        if current is None:
            problems.append(f"{qid}: distractor margin disappeared from the run")
        elif current < recorded - abs(recorded * MARGIN_TOLERANCE) - MARGIN_TOLERANCE:
            problems.append(
                f"{qid}: distractor margin narrowed: {current} < {recorded}"
            )

    for name, passed in result.assertions.items():
        if not passed:
            problems.append(f"assertion failed: {name}")
    return problems


def render(result: Result, baseline: dict[str, Any] | None) -> str:
    lines = [
        "Knowledge retrieval eval — Tier 1 (deterministic, no model)",
        "",
        f"  rank@1               {result.rank_at_1:.4f}"
        + (f"   baseline {baseline['rank_at_1']:.4f}" if baseline else ""),
        f"  rank@3               {result.rank_at_3:.4f}"
        + (f"   baseline {baseline['rank_at_3']:.4f}" if baseline else ""),
        f"  mean reciprocal rank {result.mrr:.4f}"
        + (f"   baseline {baseline['mrr']:.4f}" if baseline else ""),
        f"  ladder tokens        {result.total_ladder_tokens}"
        + (f"   baseline {baseline['total_ladder_tokens']}" if baseline else ""),
        "",
        "  Per question:",
    ]
    for qid, entry in sorted(result.per_question.items()):
        rank = entry["rank"]
        shown = "-" if rank is None else str(rank)
        marker = " " if rank == 1 or entry["kind"] == "links-only" else "!"
        lines.append(
            f"  {marker} {qid}  rank={shown:>2}  tokens={entry['ladder_tokens']:>5}  "
            f"{entry['kind']:<12} want={entry['expect_unit']}"
        )
        if rank != 1 and entry["kind"] != "links-only":
            lines.append(f"        top hit was {entry['top_unit']}")

    if result.margins:
        lines += ["", "  Distractor margins (correct score - decoy score):"]
        for qid, margin in sorted(result.margins.items()):
            note = "  <- decoy outranks the answer" if margin < 0 else ""
            lines.append(f"    {qid}  {margin:+.4f}{note}")

    lines += ["", "  Assertions:"]
    for name, passed in sorted(result.assertions.items()):
        lines.append(f"    {'pass' if passed else 'FAIL'}  {name}")

    if result.failures:
        lines += ["", "  Failures:"]
        lines += [f"    - {problem}" for problem in result.failures]
    return "\n".join(lines)


def as_baseline(result: Result) -> dict[str, Any]:
    return {
        "rank_at_1": result.rank_at_1,
        "rank_at_3": result.rank_at_3,
        "mrr": result.mrr,
        "total_ladder_tokens": result.total_ladder_tokens,
        "margins": result.margins,
        "per_question_rank": {
            qid: entry["rank"] for qid, entry in sorted(result.per_question.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-baseline", action="store_true", help="Rewrite baseline.json.")
    parser.add_argument("--json", action="store_true", help="Emit the measurements as JSON.")
    args = parser.parse_args(argv)

    result = evaluate()

    if args.update_baseline:
        BASELINE.write_text(json.dumps(as_baseline(result), indent=2) + "\n", encoding="utf-8")
        print(f"Baseline written to {BASELINE}")
        print(render(result, None))
        return 0

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else None

    if args.json:
        print(json.dumps(as_baseline(result), indent=2))
    else:
        print(render(result, baseline))

    if baseline is None:
        print("\nNo baseline recorded. Run with --update-baseline to create one.", file=sys.stderr)
        return 1

    problems = compare(result, baseline)
    if problems:
        print("\nRegressions against the baseline:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
