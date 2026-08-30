---
id: 1-identity/consumers
tier: 1
type: identity
area: consumers
title: Consumers
read_when: "Deciding whether a change breaks a caller, or who to warn before shipping it."
provenance: stated
sources:
  - docs/charter.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Three internal callers and one scheduled export depend on Ledger.

## Detail

The checkout service writes entries synchronously and expects a decision within 200ms. The
support console reads entry history. The analytics warehouse ingests a nightly dump. Finance
consumes the settlement file and treats it as authoritative.

The 200ms figure is owed to checkout as a service level, not an aspiration.

## Open questions

- none
