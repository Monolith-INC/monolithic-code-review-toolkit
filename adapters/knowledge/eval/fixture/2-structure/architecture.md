---
id: 2-structure/architecture
tier: 2
type: structure
area: architecture
title: Architecture
read_when: "Understanding the layers and which direction dependencies are allowed to point."
provenance: derived
sources:
  - docs/architecture.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Three layers: domain, application, and adapter. Dependencies point inward only.

## Layout

The domain layer holds entities and pure rules. The application layer orchestrates use cases.
The adapter layer holds HTTP handlers, the database gateway, and the currency rounding helper
used at the presentation edge.

## Rules

An inner layer never imports an outer one. A currency amount crosses layers as a minor-unit
integer; formatting and rounding for display happen in the adapter layer.

## Open questions

- none
