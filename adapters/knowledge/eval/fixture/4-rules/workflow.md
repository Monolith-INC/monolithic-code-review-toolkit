---
id: 4-rules/workflow
tier: 4
type: rules
area: workflow
title: Workflow
read_when: "Checking what a change must clear before it can merge."
provenance: stated
sources:
  - CONTRIBUTING.md
  - .github/pull_request_template.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Trunk-based with short-lived branches and a squash merge.

## Mandated

Conventional commit subjects. One reviewer approval. A green check target. Any change touching
the public OpenAPI document additionally requires review from the API owner, who checks it
against the compatibility policy before approving.

## Prohibited

Force-pushing a branch that another person has reviewed. Merging with a red pipeline.

## Enforcement

Branch protection, plus the CODEOWNERS entry that pulls in the API owner automatically.

## Open questions

- none
