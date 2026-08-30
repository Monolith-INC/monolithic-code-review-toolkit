---
title: Knowledge retrieval eval harness
ticket: MCRT-001
type: ticket
area: knowledge
status: active
created: 2026-08-30
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
