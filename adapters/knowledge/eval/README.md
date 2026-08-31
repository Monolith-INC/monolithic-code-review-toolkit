# Knowledge retrieval evaluation

The store shipped in 0.5.0 with every design choice justified by argument and none by evidence. This
measures the part a machine can measure, and documents the part it cannot.

```bash
python3.12 adapters/knowledge/eval/run_eval.py          # measure against the baseline
python3.12 adapters/knowledge/eval/run_eval.py --json   # machine-readable
python3.12 adapters/knowledge/eval/run_eval.py --update-baseline
```

Exits non-zero on a regression, on a baseline question missing from the run, or on a failed
assertion. Dependency-free — it imports the store directly, so it runs wherever the store tests run.

`--update-baseline` accepts metric movement — re-recording numbers is what the flag is for, and a
number that legitimately moved is not a defect. It still **refuses to write while an assertion
fails**, exiting 1 and leaving the existing baseline byte-identical. The assertions are not
measurements; they are invariants the fixture and the store must hold, so recording a broken one
would make the breakage the new normal and retire the check that caught it.

## Two tiers, and why

| Tier | Measures | Needs a model | Gates |
| --- | --- | --- | --- |
| **1** — `run_eval.py` | rank@1, rank@3, MRR, ladder token cost, distractor margin | No | Yes, against `baseline.json` |
| **2** — [`model_eval.md`](model_eval.md) | hit@1 (**pick**, not rank), wrong-file confidence, ladder adherence | Yes | Never |

The split is not a convenience. Two of the three metrics originally specified for this work are
judgements — whether a reader *picks* the right unit from the catalog, and whether a run answers
*confidently* from the wrong one. Neither has a faithful mechanical proxy, so Tier 1 does not claim
to measure them and Tier 2 says how to.

## What Tier 1 measures

- **rank@1 / rank@3 / MRR** — where the correct unit lands in `find`, deduplicated to units, because
  the reader's question is which *unit* to open. The links-only question is excluded from these: it
  is designed to be unfindable by search, and scoring it as a miss would punish correct behaviour.
- **Ladder token cost** — what a fixed `catalog` → `find` → `fetch` policy spends before the correct
  unit's content is in hand. Units ranked above the right one get fetched on the way down and charged
  for, which is what couples this metric to ranking quality.
- **Distractor margin** — score gap between the correct unit and its planted near-miss. Negative
  means the decoy wins. That is the mechanical *shadow* of wrong-file confidence, and it is labelled
  as a shadow because a shadow is what it is.

### The clock is pinned

The store's recency bonus is a function of how old a unit is *today*, so on the wall clock every
number here decays a little each day against a fixture that never changes. `run_eval.py` pins the
store to `EVAL_TODAY` — the date the fixture units carry — which is what makes the committed
baseline reproducible rather than a snapshot of one afternoon.

This was not hypothetical. The day after the harness merged, the date rolled over and the ladder
cost moved 20764 → 20766 on an untouched tree. Left alone it would have drifted until a rank flipped
and the harness reported a regression nobody caused.

Four assertions are pass/fail rather than scored: the links-only target is unreachable by search and
reachable by traversal, the assumed trap tops its question while carrying `provenance: assumed`, the
oversized unit truncates with a handle that advances to new content, and ordering is reproducible.

A question named in the baseline but absent from the run is a regression in its own right. Deleting
one moves no aggregate and *lowers* the token cost, so without that check the loss of coverage reads
as an improvement — which is exactly how the links-only question could have disappeared unnoticed.
Questions the baseline does not know are the opposite case: added coverage, reported but not failed.

## Measured sensitivity

A harness never shown failing is not known to measure anything. Five deliberate perturbations of the
ranking function, each run against the committed baseline:

| Perturbation | rank@1 | Caught | By which signal |
| --- | --- | --- | --- |
| Ranking inverted | 0.0000 | Yes | rank@1 |
| BM25 length normalisation disabled | 0.8182 | Yes | per-question rank |
| IDF flattened to 1 | 0.8182 | Yes | distractor margin |
| Path boost removed | 0.8182 | **No** | — |
| Recency bonus removed | 0.8182 | **No** | — |
| *Control — unmodified* | 0.8182 | *no false positive* | — |

Two findings worth carrying:

1. **The aggregates alone are too coarse.** Two of the three caught regressions left rank@1, rank@3
   and MRR untouched, and were caught only by the per-question rank comparison and the distractor
   margin. With a dozen questions, an aggregate can absorb a real change without moving.
2. **A score change that never flips a rank is invisible here.** The path boost and the recency bonus
   are small additive nudges; removing either changes scores but reorders nothing. Catching those
   would need a score fingerprint, which would also fail on every *improvement* — a change detector,
   not a regression detector. The better remedy is more questions, which is future work.

## The corpus

`fixture/` is a hand-authored store for a fictional payments service — 23 units across all five
tiers. It is synthetic on purpose: measuring wrong-file confidence needs *planted* near-misses, and a
store derived from a real repository provides no ground truth about which distractors exist.

`questions.tsv` holds twelve questions, each with exactly one correct unit and a `kind` that selects
the assertions applied.

## What the current baseline says about the store

Two questions have a negative distractor margin — the decoy outranks the answer:

- **q01** "which layer owns currency rounding" ranks `2-structure/architecture` above
  `4-rules/coding-standards`. Architecture names where the rounding *helper* lives; only the rules
  unit states which layer *owns* the rule. A reader following rank@1 gets the rule backwards.
- **q02** "payment gateway retry policy backoff" ranks `1-identity/purpose` above
  `3-mechanics/runtime-ops`, because purpose is short and mentions the gateway, and BM25 length
  normalisation rewards brevity.

Both are real retrieval weaknesses, recorded rather than tuned away. A baseline of 1.0 measures
nothing and can only ever move by accident.
