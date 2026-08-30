---
title: Core-owned review harness contracts
type: adr
status: accepted
created: 2026-08-30
feature: FEATURE-0002
---

# ADR-0007 — Core-owned review harness contracts

## Context

Claude and Codex previously carried overlapping review roles, lifecycle
validation, checkpoint formats and posting rules. Their installer flags also
accepted opaque provider-tool strings. That made a product policy dependent on
host prompts and created cross-project leakage risk for user-scoped installs.

## Decision

Define the review harness in `core/review_harness`. It owns the logical
capability registry, typed binding contract, generated JSON Schema evidence,
checkpoint lifecycle and deterministic action decision. `sources.json` version
2 replaces opaque references with typed MCP, argv, or bounded path bindings.

Claude and Codex adapters translate their respective hook payloads, agent
formats and installation paths. They may map host model names and config files,
but may not introduce product roles, capability effects or authorization rules.
The gate is MCRT-scoped: it fails closed for a provenance-bearing review write
and remains inert for unrelated manual comments.

## Consequences

- Provider configuration becomes inspectable, migratable and safe to project-scope.
- The same test fixtures can assert both adapters’ enforcement decisions.
- Existing version-1 write mappings must migrate before automated posting is
  allowed; read-only review remains available during the compatibility period.
- Hook execution remains host infrastructure. Installers must self-test it and
  document a host-level hook failure as a blocked review rather than a bypass.
