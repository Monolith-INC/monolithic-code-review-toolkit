---
id: 3-mechanics/build-tooling
tier: 3
type: mechanics
area: build-tooling
title: Build tooling
read_when: "Finding the task that builds, formats, lints, or regenerates something."
provenance: derived
sources:
  - Makefile
  - .pre-commit-config.yaml
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

A Makefile is the task runner. Every task a contributor needs has a target.

## Commands

`make bootstrap` creates the environment. `make fmt` and `make lint` run the formatter and
linter. `make generate` regenerates the SDK from the OpenAPI document. `make check` chains
format, lint, type check, and the test target.

## Detail

Pre-commit hooks run the formatter only. Everything heavier is left to the check target so a
commit is never slow.

## Open questions

- none
