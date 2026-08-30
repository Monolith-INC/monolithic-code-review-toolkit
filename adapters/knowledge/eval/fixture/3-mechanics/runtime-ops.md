---
id: 3-mechanics/runtime-ops
tier: 3
type: mechanics
area: runtime-ops
title: Runtime operations
read_when: "Understanding how Ledger is deployed, configured, retried, observed, and recovered."
provenance: derived
sources:
  - deploy/
  - docs/runbook.md
derived_from_commit: f1x7ure0
updated: 2026-08-30
version: 1
status: current
supersedes: []
links: []
---

## Summary

Three environments, configuration by environment variable, deployment by rolling update.

## Commands

`make deploy ENV=staging` promotes the current image. Production promotion is gated on a manual
approval in the pipeline and cannot be triggered from a developer machine.

## Detail

Environments are development, staging, and production. Development runs against a local
container. Staging mirrors production topology at one replica. Production runs three replicas
behind a load balancer.

Configuration is supplied entirely by environment variable. There is no configuration file in
the image. Secrets are injected by the platform secret store at pod start and are never present
in the repository or in the built image.

The payment gateway client retries on connection errors and on HTTP 502, 503, and 504. It
retries three times with exponential backoff starting at 200 milliseconds and a jitter of up to
50 milliseconds. It never retries a 4xx, because the gateway treats a repeated authorisation
request as a new attempt and a blind retry can double-charge a customer. A retry budget is
tracked per request and exhausting it surfaces as a domain error rather than an exception.

Feature flags are read at process start, not per request. Changing a flag requires a rolling
restart, which is deliberate: a flag that flips mid-batch would split a settlement run across
two behaviours.

Observability is three signals. Structured logs carry a correlation identifier threaded from the
inbound request through to the gateway call. Metrics cover request rate, error rate, duration,
and a settlement lag gauge. Traces are sampled at one percent in production and at one hundred
percent in staging.

The settlement job runs nightly at 02:00 UTC. It reads the day's closed batches, produces the
settlement file, and uploads it to the finance bucket. It is idempotent: re-running it for the
same date overwrites the file rather than appending, so a failed run can simply be run again.

The runbook for a failed settlement is to check the settlement lag gauge first, then the job
logs for the correlation identifier of the first failing batch, then re-run the job for that
date. Escalate only if the re-run fails identically.

Backups are taken hourly and retained for thirty days. A restore has been rehearsed twice and
takes approximately forty minutes for the production dataset.

## Open questions

- Whether the one percent trace sample is enough to diagnose a rare settlement failure.
