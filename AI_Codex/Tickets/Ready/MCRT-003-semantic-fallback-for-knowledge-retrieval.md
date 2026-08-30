---
title: Semantic fallback for knowledge retrieval
ticket: MCRT-003
type: ticket
area: knowledge
status: ready
created: 2026-08-30
feature: project-knowledge
tags:
  - knowledge
  - retrieval
  - deferred
---

# MCRT-003 — Semantic fallback for knowledge retrieval

## Context

Retrieval is lexical-first by design: BM25 over section text, a path boost, deterministic ordering.
That choice is not a limitation to be lifted — it is what gives retrieval a **verifiable failure
mode**. When a lexical query misses, `matched_terms` says which terms matched and which did not, and
the guidance response names the vocabulary that exists. The agent can diagnose its own bad query.

Embeddings have no equivalent. A vector search that returns the wrong unit returns it with a
plausible score and no account of why, which is precisely the wrong-file-confidence failure the
store exists to avoid.

So this ticket is **a fallback, never a replacement**, and it is gated on evidence that lexical
retrieval actually misses in practice.

## Trigger condition

Start this only when MCRT-001's harness shows a material class of questions where the correct unit
exists in the store and lexical retrieval cannot reach it — paraphrase, synonym, or vocabulary
mismatch between how a reviewer asks and how the unit is written.

If the miss class is small, the cheaper fix is almost always better and should be tried first:
improve `read_when` wording, add an `aliases` frontmatter field, or widen the guidance response's
near-miss suggestions. Exhaust those before adding a vector index.

## Requirements

- Lexical runs first, always. Semantic search is consulted only when lexical returns no hits, and
  the response says plainly that it did.
- A semantic hit is visibly distinguished from a lexical one, and carries no `matched_terms` claim
  it cannot support.
- The store remains usable with no embeddings present. Nothing about the file format changes, and
  no host is required to run a model to read the store.
- Any index is derived, rebuildable, and gitignored. Embeddings are never the source of truth and
  are never committed.
- No network call at review time by default. A reviewer's retrieval path must not depend on an
  external service being reachable.
- Determinism is preserved where it exists: the lexical path's ordering must not change.

## Definition of Done

- The evidence that triggered this is recorded in the ticket: the question class lexical retrieval
  missed, and the cheaper fixes tried first and why they were insufficient.
- The harness shows the fallback improves hit@1 on that class **without** raising the
  wrong-file-confidence rate. A fallback that finds more and misleads more is a regression.
- Tests cover: lexical hits short-circuit the fallback entirely; no embeddings present degrades to
  lexical-only; a semantic hit is labelled as such.
- ADR-0006's rejection of embeddings is superseded by a new ADR stating what changed.

## Out of scope

- Replacing BM25. The ladder's first rung stays lexical.
- Semantic search over the repository's source code. This is about the knowledge store only.

## References

- `adapters/knowledge/knowledge_store.py` — `find`, `_guidance`
- `AI_Codex/Architecture/ADR/ADR-0006-project-knowledge-store-and-lookup-contract.md` — Options considered
- `AI_Codex/Tickets/Ready/MCRT-001-knowledge-retrieval-eval-harness.md`
