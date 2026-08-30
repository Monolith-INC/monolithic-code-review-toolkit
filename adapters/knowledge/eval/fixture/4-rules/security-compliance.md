---
id: 4-rules/security-compliance
tier: 4
type: rules
area: security-compliance
title: Security and compliance
read_when: "Checking how credentials, personal data, or regulated fields must be handled."
provenance: stated
sources:
  - docs/security.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Ledger is in scope for card-industry audit because it stores authorisation references.

## Mandated

Secrets come from the platform secret store, injected at runtime. Card numbers are never stored;
only the gateway's opaque authorisation reference is. Access to production data requires a
ticketed, time-boxed grant.

## Prohibited

Any credential in the repository, in an environment file, or in a log line. Printing an
authorisation reference at info level.

## Enforcement

Secret scanning on every push, and a log redaction filter applied to the shared formatter.

## Open questions

- none
