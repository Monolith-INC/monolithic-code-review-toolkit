---
title: Knowledge retrieval eval harness
ticket: MCRT-001
type: ticket
area: knowledge
status: closed
created: 2026-08-30
closed: 2026-08-30
feature: project-knowledge
tags:
  - knowledge
  - retrieval
  - evaluation
---

# MCRT-001 — Knowledge retrieval eval harness

## Context

0.5.0 shipped the project knowledge store and its lookup contract without any measurement of whether
retrieval actually works. Every design choice in it — the three-rung cost ladder, BM25 with a path
boost, section-grained hits, `matched_terms`, guidance on empty results — is currently justified by
argument rather than by evidence.

That is the wrong footing for the one component whose failure mode is silent. A review that fetches
a plausible but wrong unit does not error; it produces a confident finding citing the wrong rule.

Three metrics decide whether the contract is good. Only the third catches that failure.

## Goal

Make retrieval quality measurable, so a change to ranking or to the tool descriptions can be shown
to help or hurt rather than argued about.

## Requirements

- A fixture store with enough units to make ranking meaningful, and a question set with a single
  verifiable correct unit (and where applicable, anchor) per question.
- **hit@1 on the routing call** — how often `knowledge_catalog` alone lets a reader pick the right
  unit. This measures whether `read_when` is doing its job, which is the field the whole ladder
  rests on.
- **Tokens-to-correct-answer** — total tokens spent across all calls until the correct unit content
  is in hand. This is the metric to optimise; the ladder exists to lower it.
- **Wrong-file-confidence rate** — how often a run answers from a plausible but incorrect unit
  without signalling uncertainty. This is the metric that silently poisons downstream work, so it is
  reported even when it is zero.
- Deterministic and runnable offline **for the ranking mechanics**. See the correction below: this
  requirement cannot cover all three metrics, and pretending otherwise is what produced a
  contradictory ticket.
- Runs from the repository's existing runner, with no new third-party dependency beyond the ones
  `adapters/knowledge` already declares.

## Correction — the original requirements contradicted each other

As filed, this ticket demanded three metrics **and** stated the harness "must not need a live model."
Those cannot both hold, and the contradiction was only visible once someone tried to build it:

| Metric as filed | Mechanical? |
| --- | --- |
| hit@1 on the routing call — does `catalog` alone let a reader **pick** the right unit | **No.** Picking is a judgement. A machine can only measure whether `find` *ranks* it first, which is a claim about a different call |
| Tokens-to-correct-answer | **Only** under a fixed scripted policy. A real agent's path is its own |
| Wrong-file-confidence — answers from a wrong unit **without signalling uncertainty** | **No.** Needs an answer and an uncertainty signal, both model behaviours |

The work is therefore split into two tiers, and neither is presented as the other:

- **Tier 1** (`run_eval.py`) — deterministic, offline, gated on a committed baseline. Measures
  rank@1/@3, mean reciprocal rank, ladder token cost, and distractor margin.
- **Tier 2** (`model_eval.md`) — a documented procedure, run by hand, that measures the real hit@1
  (pick) and wrong-file-confidence with a model in the loop. It gates nothing.

"rank@1" is deliberately not called "hit@1" anywhere in the harness, because they are different
claims and conflating them is how a measurement starts lying.

## Definition of Done

- `adapters/knowledge/eval/` holds the fixture store, the question set, and the runner.
- A single command reports all three metrics and exits non-zero on regression against a committed
  baseline.
- The baseline is committed, so a ranking change shows up as a diff in the numbers.
- At least one question in the set is designed to be answerable only via `knowledge_links`, so
  backlink traversal is covered rather than assumed.
- At least one question targets a `provenance: assumed` unit and asserts that the run does not
  present it as a citable rule.
- `docs/quality-gates.md` states what the harness proves and what it does not.
- The known-limitation entry in `docs/specs/product-requirements.md` is replaced by the measurement.

## Out of scope

- Wiring the harness into CI as a blocking gate. Establish the baseline and its variance first; a
  flaky quality gate is worse than none.
- Measuring end-to-end review quality. This measures retrieval, not whether the finding was right.

## References

- `adapters/knowledge/README.md`
- `AI_Codex/Architecture/ADR/ADR-0006-project-knowledge-store-and-lookup-contract.md`
- `docs/specs/product-requirements.md` — Known limitations

## Outcome

Tier 1 delivered and Tier 2 specified. Two results worth carrying forward:

1. **The store has two real retrieval weaknesses**, recorded in the baseline rather than tuned away.
   For "which layer owns currency rounding" the architecture unit outranks the rules unit that
   actually states the rule; for the gateway retry question a short identity unit outranks the
   operations unit. Both have a negative distractor margin. A baseline of 1.0 would have measured
   nothing.
2. **The harness's own sensitivity is bounded and now measured.** Of five deliberate ranking
   perturbations, three are caught and two are not. The two misses change scores without reordering
   anything, and catching them would need a score fingerprint that fails on improvements too. More
   questions is the honest remedy, and it is future work.

The aggregate metrics alone proved too coarse: two of the three caught regressions left rank@1,
rank@3 and MRR untouched and were caught only by the per-question rank comparison and the distractor
margin. Both of those checks were added because the sensitivity sweep showed they were needed.

## Review round

Review found two defects in the harness, and both were of the harness's own kind — failures to
notice. Each was reproduced before being fixed, in `b2f004b`.

1. **A deleted question removed coverage silently.** `compare()` exempted links-only questions from
   the per-question rank check because their rank is legitimately `null`, and the exemption also
   swallowed the case where the question was *gone*. Deleting `q08` left rank@1 at 0.8182 and MRR at
   0.9091, dropped the only link-traversal assertion, and *lowered* the ladder cost from 20764 to
   18361 — so losing coverage read as an improvement, and the run exited 0. Presence is now checked
   before any exemption applies.
2. **`--update-baseline` would record a broken invariant.** With the links-only edge severed it
   printed `FAIL q08:links-only` and wrote the baseline anyway, contradicting its own documented
   behaviour. The flag exists to accept *metric* movement; an assertion is an invariant, and
   recording a broken one makes the breakage the new normal and retires the check that caught it. It
   now refuses, exits 1, and leaves the file byte-identical.

Both fixes changed no measurement — `baseline.json` came out byte-identical, which is what proves the
fix altered only the comparison and not the store.

A third defect surfaced the next day, from the harness simply being run again: the store's recency
bonus reads the wall clock, so a frozen fixture scored differently once the date rolled over and the
ladder cost moved 20764 → 20766 on an untouched tree. A baseline that decays on its own is not a
baseline; left alone it would have drifted until a flipped rank reported a regression nobody caused.
The store now takes one injectable clock and the eval pins it to the fixture's date.

The generalisable lesson is the one the sensitivity sweep had already started: this harness's blind
spots are all shaped like *silence*. Every defect found in it so far — the null-rank false positive,
the deleted question, the recorded invariant, the drifting clock — was a case of the runner reporting
success while measuring less than it claimed, or measuring something other than what it named.
Future changes to it are worth reviewing against that question specifically: what would this still
call green?
