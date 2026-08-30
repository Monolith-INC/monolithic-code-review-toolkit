---
title: SQLite + FTS5 backing for the knowledge store
ticket: MCRT-002
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

# MCRT-002 — SQLite + FTS5 backing for the knowledge store

## Context

`find` currently builds its BM25 index in-process on first call and invalidates it on an mtime and
size signature. At the size a knowledge store actually reaches — dozens of units, a few hundred
sections — that is the right trade: files stay the source of truth, the tree stays greppable, and
there is no second copy of the data to fall out of sync.

It stops being the right trade when a caller needs a real `WHERE`: filtered, joined, or aggregated
queries across units. Scanning every unit to answer "which `rules` units cite a source under
`src/auth/` and were updated this quarter" is where files stop scaling.

**This ticket is deliberately not ready to start.** It is recorded so the trigger is written down
rather than rediscovered, and so nobody adds a database because it felt more serious.

## Trigger conditions

Start this only when at least one holds, with evidence:

- A consuming skill needs a filtered or joined query that the fixed facet set cannot express, and
  the need recurs rather than being one caller's convenience.
- The eval harness (MCRT-001) shows in-process index construction is a material share of
  tokens-to-correct-answer or wall time on a realistic store.
- A store in real use exceeds roughly a thousand sections, where a full scan per query is no longer
  negligible.

Absent all three, close this as not needed. That is a legitimate outcome.

## Requirements

- Files remain the source of truth. The database is a derived index, rebuildable from the tree, and
  deleting it loses nothing.
- The store stays greppable and hand-editable. Lexical addressing without tooling is a contract
  from ADR-0006, not a convenience.
- The index self-heals: a stale or corrupt database is detected and rebuilt rather than served.
- No new third-party dependency — `sqlite3` is in the standard library, and FTS5 is compiled into
  most builds. A build without FTS5 must fall back to the in-process index, not fail.
- Ranking stays deterministic, with the same stable tie-break by path, so results remain cacheable
  and the eval baseline stays comparable.

## Definition of Done

- The trigger condition that justified starting is recorded in the ticket before any code.
- `find` results are unchanged for the existing eval question set, or the baseline is updated with
  the ranking change explained.
- Tests cover: a fresh build, a rebuild after external edits, a corrupt database, and a build
  without FTS5 available.
- ADR-0006's deferral row is superseded by a new ADR recording what changed the decision.

## Out of scope

- Storing unit *content* in the database as the authority. It indexes; the files hold.
- Replacing the facet parameters with a query DSL. Free-form query parameters produce malformed
  queries at a high rate and cannot be validated cheaply — that rejection stands independently of
  the storage engine.

## References

- `adapters/knowledge/knowledge_store.py` — `find`
- `AI_Codex/Architecture/ADR/ADR-0006-project-knowledge-store-and-lookup-contract.md` — Options considered
