---
id: 2-structure/topology
tier: 2
type: structure
area: topology
title: Topology
read_when: "Locating which package a change belongs in, or how the services relate."
provenance: derived
sources:
  - pyproject.toml
  - packages/
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

A single repository with four packages: core, api, jobs, and clients.

## Layout

`core` holds entry writing and domain rules. `api` is the HTTP surface. `jobs` holds scheduled
work including settlement. `clients` holds the generated SDK.

## Rules

`core` depends on nothing internal. Everything else depends on `core`.

## Open questions

- none
