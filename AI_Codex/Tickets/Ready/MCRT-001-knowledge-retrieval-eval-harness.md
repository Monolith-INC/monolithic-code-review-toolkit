---
title: Knowledge retrieval eval harness
ticket: MCRT-001
type: ticket
area: knowledge
status: ready
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
- Deterministic and runnable offline. Ranking is deterministic by contract, so the harness must not
  need a live model to score retrieval mechanics.
- Runs from the repository's existing runner, with no new third-party dependency beyond the ones
  `adapters/knowledge` already declares.

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
