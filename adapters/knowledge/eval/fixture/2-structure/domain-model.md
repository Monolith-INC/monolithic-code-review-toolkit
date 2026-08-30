---
id: 2-structure/domain-model
tier: 2
type: structure
area: domain-model
title: Domain model
read_when: "Deciding which entity owns a rule, or what an invariant means in Ledger's language."
provenance: derived
sources:
  - packages/core/src/entities.py
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links:
  - "[[2-structure/settlement-context]]"
---

## Summary

The core entities are Entry, Account, and Batch. An Entry is immutable once written.

## Layout

Entries are grouped into Batches. A Batch is closed when the settlement job runs. Accounts carry
a running balance derived from entries, never stored independently.

## Rules

An Entry is never updated or deleted. A correction is a new compensating Entry.

Reversals are deliberately not modelled here. They are handled elsewhere, in the area that also
owns disputes; see [[2-structure/settlement-context]] for how that boundary is drawn and why.

## Open questions

- none
