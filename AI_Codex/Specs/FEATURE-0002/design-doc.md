---
type: design-doc
feature: FEATURE-0002
status: accepted
---

# Design — Core-owned review harness

## Goals

Keep review semantics independent of the model host; make provider references
validatable; and make an approved finding at-most-once externally visible.

## Design

`core/review_harness` owns contract validation, JSON Schema evidence, capability
effect classification, checkpoint lifecycle and the pure action decision.
Adapters translate native hook events and render native agents/configuration.
The source of provider binding is the reviewed workspace's `sources.json` v2,
never a user-scoped installer argument.

Pre-tool hooks call the gate under a checkpoint lock. They record an attempt
before the host performs the write. Post-tool hooks record success or failure.
The result is intentionally MCRT-scoped: a normal manual comment is not gated.

## Threat model

The design blocks unapproved, replayed, mis-targeted, stale-binding and
unregistered MCRT writes. It does not claim to defend against a user disabling
the host hook or executing a provider action outside the configured host; that
boundary is documented and installers self-test the hook path.
