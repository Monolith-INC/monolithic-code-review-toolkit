---
title: Ledger knowledge store (evaluation fixture)
schema_version: 1
derived_from_commit: f1x7ure0
updated: 2026-08-30
tiers_present: [1, 2, 3, 4, 5]
---

# Evaluation fixture — Ledger

A synthetic knowledge store for a fictional payments service. It exists to measure retrieval, not to
describe any real project, and it is hand-authored so that the correct answer to every question is
known and the near-misses are deliberate.

## Units by provenance

- `derived` — 13
- `stated` — 9
- `assumed` — 1 (`5-evolution/risks`, the trap for the provenance gate)

## Deliberately planted

- Five distractor pairs, where a decoy unit shares vocabulary with the answer.
- One target reachable only through `knowledge_links` (`2-structure/settlement-context`).
- One unit long enough to force `fetch` truncation (`3-mechanics/runtime-ops`).

## Omitted

No `1-identity/*` unit records service levels separately; they live in `consumers`. Nothing here is
omitted for lack of evidence, because nothing here was derived from a real tree.
