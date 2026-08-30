---
id: 4-rules/nfr-budgets
tier: 4
type: rules
area: nfr-budgets
title: Non-functional budgets
read_when: "Checking whether a change is allowed to cost latency, memory, or availability."
provenance: stated
sources:
  - docs/slo.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Budgets are owed to consumers and treated as requirements, not goals.

## Mandated

Entry write responds within 200 milliseconds at the 99th percentile. The read API responds
within 400 milliseconds at the 99th percentile. Availability target is 99.9 percent monthly.
The settlement file is delivered before 04:00 UTC.

## Prohibited

Adding a synchronous external call to the entry write path. That path has no budget left.

## Enforcement

A load test in the pipeline for the write path, and an alert on the delivery deadline.

## Open questions

- none
