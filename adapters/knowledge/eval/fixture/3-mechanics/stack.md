---
id: 3-mechanics/stack
tier: 3
type: mechanics
area: stack
title: Stack
read_when: "Checking which runtime or framework version a change can assume."
provenance: derived
sources:
  - pyproject.toml
  - .python-version
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Python 3.12, FastAPI for the HTTP surface, PostgreSQL 16 for storage.

## Commands

The interpreter is pinned in `.python-version`; the virtual environment is created by the
bootstrap task.

## Detail

Type checking is strict across `core` and advisory elsewhere. There is no ORM: queries are
written by hand against the gateway module.

## Open questions

- none
