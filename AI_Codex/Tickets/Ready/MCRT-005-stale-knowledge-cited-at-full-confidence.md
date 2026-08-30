---
title: Stale knowledge is cited at full confidence
ticket: MCRT-005
type: bug
area: knowledge
status: ready
severity: high
created: 2026-08-30
feature: project-knowledge
tags:
  - knowledge
  - bug
  - evidence
---

# MCRT-005 — Stale knowledge is cited at full confidence

## Context

The store records everything needed to detect staleness — `knowledge.derived_from_commit` in
`sources.json`, and a `sources` list on every unit naming the repository paths it was derived from —
and **nothing ever evaluates it at read time**.

`discover-project-knowledge` uses those fields when a human explicitly re-runs it. No consuming
skill checks them. So the failure looks like this:

1. A store is built at commit `abc123`. `2-structure/architecture` records a dependency rule with
   `provenance: derived`, sourced from `docs/architecture.md`.
2. Three months of commits change that rule. Nobody re-runs discovery.
3. A review reads the unit, sees `provenance: derived`, and is told by the skills that `derived`
   units may be cited as project rules. It reports a finding against a diff that follows the
   *current* architecture, citing a rule that has not been true since April.

This is worse than having no store. The finding is confidently wrong, carries a unit id that makes
it look checkable, and — on `review-story-postflight` — can be posted to a pull request.

The store-drift rule in the shared "Project knowledge" block does not cover this. It fires when the
reviewer *notices* the disagreement. The whole problem is the case where nothing looks wrong.

## Impact

`provenance` was designed as the trust boundary, and it silently degrades: a unit's provenance
describes how its facts were established, not whether they are still true. `derived` and `stated`
both decay, and today both keep asserting full citability forever.

## Requirements

- A consuming skill can determine, cheaply, whether the unit it is about to cite may be stale —
  without re-deriving anything and without reading the whole store.
- Staleness is computed from evidence already recorded: `git diff --name-only <derived_from_commit>...HEAD`
  intersected against each unit's `sources`. A unit whose sources did not change is not stale, however
  old the store is; a unit whose sources changed yesterday is, however recent.
- A unit detected as stale **cannot support a finding at full confidence**. It degrades to the same
  disposition as `provenance: assumed`: usable as context, reported under local uncertainty, never
  posted as a rule the author violated.
- The signal reaches the reader at the point of use. A unit fetched through the MCP adapter carries
  its staleness in the response, the same way `provenance: assumed` already does.
- The no-tooling path degrades honestly rather than silently: without the adapter, the skills state
  what they could not check.
- A store with no `derived_from_commit`, or one whose recorded commit is unreachable (history
  rewritten, shallow clone), is treated as unverifiable — not as fresh.

## Definition of Done

- `knowledge_fetch` reports staleness per unit, computed from the unit's own `sources`, and prefixes
  a stale unit with the same kind of warning it already gives an `assumed` one.
- The shared "Project knowledge" block in the four lifecycle skills, and the targeted sections in
  the other five, state the degraded disposition for a stale unit.
- Tests cover: sources unchanged since the recorded commit (not stale); sources changed (stale);
  no `derived_from_commit` recorded (unverifiable); recorded commit unreachable (unverifiable);
  a unit with an empty `sources` list (unverifiable, because nothing can invalidate it).
- The staleness check adds no measurable cost to a `catalog` call, which must stay on its token
  budget — compute it on `fetch`, or once per run against the changed-path set.
- `docs/specs/product-requirements.md` drops the known-limitation wording for staleness and points
  at the implemented behaviour.

## Out of scope

- Forcing or scheduling a refresh. The fix is to stop trusting stale units, not to guarantee
  freshness — a store the team has not updated is a fact of life, and the review must survive it.
- Auto-re-deriving a stale unit mid-review. Discovery asks questions and writes files; a review is
  not the place for either.

## References

- `plugins/monolithic-code-review-toolkit/skills/discover-project-knowledge/SKILL.md` — refresh contract
- `adapters/knowledge/knowledge_store.py` — `fetch`
- `AI_Codex/Architecture/ADR/ADR-0006-project-knowledge-store-and-lookup-contract.md` — Consequences
