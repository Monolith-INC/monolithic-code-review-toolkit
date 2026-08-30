---
id: 3-mechanics/data
tier: 3
type: mechanics
area: data
title: Data
read_when: "Adding or changing a table, a migration, or a query."
provenance: derived
sources:
  - core/migrations/
  - Makefile
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

PostgreSQL with hand-written migrations applied in order by a small runner.

## Commands

`make migrate` applies pending migrations. `make migrate-new NAME=...` scaffolds an empty
migration file with the next sequence number. There is no autogeneration; migrations are written
by hand because the schema is small and the ordering matters.

## Detail

Every migration must be forward-only. The entries table is append-only and partitioned by month.

## Open questions

- none
