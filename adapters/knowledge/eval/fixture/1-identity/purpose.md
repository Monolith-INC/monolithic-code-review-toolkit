---
id: 1-identity/purpose
tier: 1
type: identity
area: purpose
title: Purpose
read_when: "Understanding what Ledger is for before judging whether a change serves it."
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

Ledger records money movement for the marketplace and produces the daily settlement file the
finance team reconciles against the bank statement.

## Detail

It is a system of record, not a payment gateway. It never holds funds and never contacts a card
network directly; it observes what the gateway reports and writes immutable entries.

Lifecycle stage is maintenance. The ledger schema has been stable for two years and changes are
expected to be additive.

## Open questions

- none
