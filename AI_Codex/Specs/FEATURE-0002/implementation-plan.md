---
type: implementation-plan
feature: FEATURE-0002
status: in-progress
---

# Implementation Plan — FEATURE-0002

1. Define and test the core contract registry, schema snapshot and conservative
   `sources.json` migration.
2. Implement identity-bound checkpoints and the deterministic, one-use action
   gate.
3. Translate Claude and Codex native hooks into the core event contract; add a
   Codex entry skill.
4. Replace raw tool-string documentation with typed bindings and update adapter
   installation guidance.
5. Run core, adapter, payload, plugin and host smoke checks; publish release
   notes only after a human-approved disposable-PR pilot.

Rollback removes project overlays/hooks through their managed installer records
and leaves portable skills and repository knowledge untouched.
