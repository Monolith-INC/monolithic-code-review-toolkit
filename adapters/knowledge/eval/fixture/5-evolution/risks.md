---
id: 5-evolution/risks
tier: 5
type: evolution
area: risks
title: Risks
read_when: "Weighing whether an area is fragile before changing it — inferred, not established."
provenance: assumed
sources: []
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

This unit is inference, not evidence. Nothing here was confirmed with the team.

## Signals

The nightly settlement job appears to have no standby and appears to run on a single schedule
with no second attempt, which would make it a single point of failure for the finance deadline.
This was inferred from the deployment manifest alone.

## Detail

Whether a failed settlement run genuinely threatens the delivery deadline depends on how much
slack sits between 02:00 and the 04:00 obligation, and on whether anyone is watching overnight.
Neither was established.

## Open questions

- Is there a manual fallback for settlement, and who would run it?
- Does the overnight rota actually watch the settlement lag gauge?
