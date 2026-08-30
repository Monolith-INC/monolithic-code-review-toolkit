---
id: 2-structure/directory-conventions
tier: 2
type: structure
area: directory-conventions
title: Directory conventions
read_when: "Deciding where a new file belongs, or whether a path is authored, generated, or vendored."
provenance: derived
sources:
  - Makefile
  - packages/clients/README.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Authored code lives under `packages/*/src`. Generated output is confined to two directories.

## Layout

`packages/clients/generated/` holds the SDK emitted from the OpenAPI document. `core/migrations/`
holds migration files, which are authored but never edited after merge.

## Rules

Never hand-edit anything under `packages/clients/generated/`; regenerate it instead. A change
that edits a generated file and its source in the same commit is a mistake, not a shortcut.
Vendored third-party code lives under `third_party/` and is updated only by version bump.

## Open questions

- none
