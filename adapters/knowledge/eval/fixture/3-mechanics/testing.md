---
id: 3-mechanics/testing
tier: 3
type: mechanics
area: testing
title: Testing
read_when: "Deciding whether a change needs a test, or which command actually runs the suite."
provenance: derived
sources:
  - Makefile
  - tests/conftest.py
  - .github/workflows/ci.yml
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Pytest, with a thin integration layer against a disposable PostgreSQL container.

## Commands

`make test` runs the unit suite. `make test-integration` starts the container and runs the
integration suite; it is the command CI uses and the one to run before opening a pull request.

## Detail

Fixtures live in `tests/conftest.py`. The settlement job has golden-file tests: a recorded input
batch and its expected settlement output. Coverage is reported but not gated.

## Open questions

- none
