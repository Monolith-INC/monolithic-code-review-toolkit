---
id: 2-structure/settlement-context
tier: 2
type: structure
area: boundaries
title: Settlement context
read_when: "Understanding where chargeback and clawback handling lives, and why it sits outside core."
provenance: derived
sources:
  - packages/jobs/src/chargeback.py
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Chargeback and clawback handling forms its own bounded area with its own vocabulary.

## Layout

A chargeback arrives from the gateway asynchronously, days after the original authorisation. It
produces a clawback record, which the settlement file reports separately from ordinary movement.

## Rules

Clawback records never mutate the original authorisation. They are additive, and the finance
team reconciles them as a distinct line.

## Open questions

- none
