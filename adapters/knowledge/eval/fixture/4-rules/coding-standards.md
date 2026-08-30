---
id: 4-rules/coding-standards
tier: 4
type: rules
area: coding-standards
title: Coding standards
read_when: "Checking whether a pattern is mandated or prohibited before writing or reviewing it."
provenance: stated
sources:
  - CONTRIBUTING.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

A small set of rules the team has agreed and written down, enforced by review.

## Mandated

Money is represented as a minor-unit integer with an explicit currency, never as a float and
never as a bare integer. Currency rounding is owned by the domain layer and performed exactly
once, at the point an amount is split; the adapter layer formats but must never round.

Every public function states its failure outcomes in its signature.

## Prohibited

Floating point for monetary amounts, anywhere. Implicit currency. Rounding a second time
downstream of the domain split, which is how a settlement file drifts by a penny per line.

## Enforcement

Review, plus a lint rule that rejects `float` in the `core` package.

## Open questions

- none
