---
id: 3-mechanics/contracts
tier: 3
type: mechanics
area: contracts
title: Contracts
read_when: "Deciding whether a change to the public surface is allowed, and what it obliges you to do."
provenance: derived
sources:
  - openapi.yaml
  - docs/versioning.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

One OpenAPI document describes the public surface. The SDK is generated from it.

## Commands

`make generate` re-emits the SDK after an OpenAPI change.

## Detail

The compatibility policy is additive-only within a major version. A field may be added; a field
may not be removed, renamed, or have its type narrowed. A breaking change requires a new major
path prefix and a deprecation window of two release cycles, during which both are served.

## Open questions

- none
