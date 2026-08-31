---
name: mcrt-review
description: Start a contract-bound Monolithic Code Review Toolkit run through the installed Codex review harness.
---

# MCRT review harness

Accept a structured review request only. Its workspace must contain a validated
`.monolithic-code-review/sources.json` v2 binding document. Delegate the request
to `mcrt_review_orchestrator`; it owns checkpoint creation, worker sequencing,
quota pauses, and the approval gate. Never post a review finding directly.

The request must identify the absolute workspace and review type. Post-flight
reviews additionally require a pull-request id; task, story, and feature reviews
require a work-item id. Provider access is resolved from the project binding
document at runtime, not from user-scoped agent configuration.
