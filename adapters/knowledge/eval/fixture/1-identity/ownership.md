---
id: 1-identity/ownership
tier: 1
type: identity
area: ownership
title: Ownership
read_when: "Finding who maintains a area of Ledger, or who to page when something breaks out of hours."
provenance: stated
sources:
  - CODEOWNERS
  - docs/oncall.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

The payments platform team maintains Ledger. CODEOWNERS routes review by directory.

## Detail

Entry writing and the settlement job are owned by the payments platform team. The support
console read API is co-owned with the support tooling team.

When the nightly settlement job fails, the payments platform on-call rota is paged directly
through the incident tool. Do not route settlement failures through the general engineering
channel; the rota is the escalation path and it is staffed overnight.

## Open questions

- none
