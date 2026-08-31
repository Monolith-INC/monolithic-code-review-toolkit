---
type: tech-spec
feature: FEATURE-0002
status: accepted
---

# Technical Specification — Review harness

## Components

- `contracts.py`: role/capability registry, typed binding validator and v1 migration.
- `schemas.py`: JSON Schema evidence derived from the registry.
- `gate.py`: side-effect-free authorization decision.
- `checkpoints.py`: atomic checkpoint persistence, authorization consumption,
  inspection, resume, abandon and outcome recording.
- host adapters: only payload normalization, agent rendering and installation.

## Invariants

All MCRT post attempts must bind the same workspace, repository, PR and binding
digest as the approval checkpoint. A finding may be attempted once. A terminal
checkpoint cannot resume or silently reopen. Product role names and capability
effects may not be declared below `adapters/`.

## Failure handling

Malformed v2 documents, locked/invalid checkpoints and unregistered marked
writes deny the action. Legacy v1 behavior remains read-only. Installer changes
must be preflighted and reversible; a host hook failure is reported as blocked
rather than being treated as approval.
