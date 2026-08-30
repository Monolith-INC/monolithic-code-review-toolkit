---
id: 5-evolution/tech-debt
tier: 5
type: evolution
area: tech-debt
title: Technical debt
read_when: "Checking whether an awkward area is known debt with a plan, or simply unexamined."
provenance: stated
sources:
  - docs/debt.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Three registered items, each with an owner and a stated intent.

## Signals

The settlement job is one long function. It is understood, tested by golden file, and
deliberately left alone until the reporting change lands.

## Detail

The support console read API predates the layering rule and reaches the gateway directly. It is
scheduled for migration. The `third_party/` currency table is a vendored snapshot that nobody
has needed to update in eighteen months.

## Open questions

- none
