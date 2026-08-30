---
title: Orchestrator workers read the knowledge store directly
ticket: MCRT-004
type: ticket
area: adapters
status: ready
created: 2026-08-30
feature: project-knowledge
tags:
  - knowledge
  - adapters
  - agent-governance
---

# MCRT-004 — Orchestrator workers read the knowledge store directly

## Context

The Claude and Codex review orchestrators run isolated workers that execute the portable skills.
Because the skills now consult the knowledge store, the workers inherit that behaviour through the
no-tooling path — `catalog.tsv` plus `Grep` plus `Read`, all of which `mcrt-review-validator` and
`mcrt-review-discovery` already hold.

So this is an optimisation, not a gap: the workers can already reach every fact. What they cannot do
is reach it cheaply. Grepping a store is measurably worse than a ranked `find`, and a worker on a
token budget is exactly where the cost ladder pays.

Deferred out of 0.5.0 on purpose. A worker's `tools:` frontmatter is a security boundary, and the
tool surface had not been exercised against a real store yet. Widening it before the contract has
settled would be granting access on the strength of a design rather than a track record.

## Requirements

- `mcrt-review-validator` and `mcrt-review-discovery` gain the **four read tools only** —
  `knowledge_catalog`, `knowledge_find`, `knowledge_fetch`, `knowledge_links`. Never
  `knowledge_put`, `knowledge_patch`, or `knowledge_add`.
- `mcrt-review-adversarial` gains the same four. Its job is checking a finding against primary
  sources, and a cited unit id is a primary source it currently has to grep for.
- `mcrt-review-poster` gains **none**. It writes comments; it has no reason to read the store, and
  its tool list should stay as narrow as it is.
- The grant follows the existing placeholder mechanism, so a repository without the knowledge
  adapter installed gets workers with no knowledge tools rather than workers referencing tools that
  do not exist.
- A worker that was not granted a tool says so rather than inferring the capability works — the
  existing "a missing tool is a finding, not an obstacle" rule applies unchanged.

## Definition of Done

- The three read workers carry the four read tools; the poster carries none.
- Installer tests assert the grant per worker, including that no worker receives a write tool.
- An install without the knowledge adapter produces worker definitions with no knowledge tools and
  no dangling placeholder.
- The Claude adapter README documents the grant and why the poster is excluded.

## Related: tool grants that already do not match their contracts

While specifying this, three pre-existing mismatches surfaced in the same files. They are not caused
by this ticket and should be fixed on their own, but this is where they were found:

- `mcrt-review-discovery`, `mcrt-review-validator` and `mcrt-review-adversarial` all hold unscoped
  `Write`, while `mcrt-review-adversarial` states "Your only write is your phase-result JSON". The
  guard protects checkpoint integrity, not arbitrary files.
- All four workers hold `Bash`, including the poster, whose hard limits forbid editing source,
  staging, and committing. The `PreToolUse` hook guards pull-request writes specifically; git state
  is on the honour system.
- The loosest grant sits on the strongest model: `mcrt-review-adversarial` is `opus` with `Write`
  and `Bash`, and its job is judgement over a frozen packet.

## Out of scope

- Changing what the workers do with project knowledge. The behaviour lives in the portable skills;
  this only changes how efficiently the workers reach it.
- The three mismatches above. Recorded here because this is where they were found, to be filed and
  fixed separately.

## References

- `adapters/claude/agents/*.md`
- `adapters/codex/agents/*.toml`
- `adapters/claude/install_claude_adapter.py` — placeholder substitution
- `adapters/knowledge/README.md`
