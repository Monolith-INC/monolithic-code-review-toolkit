# Implementation Plan

## Codex Review Orchestrator for the Monolithic Code Review Toolkit

**Summary:**

Create a distributable Codex companion adapter that orchestrates all existing review flows: task, story preflight/postflight, feature, PR preparation, and PR-comment triage. It will use sequential, isolated workers; preserve the toolkit’s requirements-first and evidence-verdict rules; and require explicit human approval before any PR comment is posted or code is changed.

Persist this implementation plan in a new AI_Codex/Agent_Reports ledger entry and keep a separate durable execution checkpoint in AI_Codex/Agent_Sessions. Preserve all current dirty-worktree changes.

**Implementation changes:**

Add a Codex adapter beside the portable plugin, with an installer that registers named custom agents project-locally or user-locally without overwriting unrelated configuration. Require agents.max_depth = 2.
Add these roles:
mcrt_review_orchestrator — Terra/medium; accepts structured review input, controls lifecycle, checkpoints, quotas, and approvals; never reviews code or posts comments itself.
mcrt_review_discovery — Luna/medium; read-only, invoked only when setup/capability/diff inventory is unknown or large.
mcrt_review_validator — Terra/medium; read-only, selects and executes the applicable toolkit lifecycle skill, collects requirement evidence, and returns structured findings.
mcrt_review_adversarial — Sol/high, once; independently challenges only candidate verified findings and returns accepted, rejected, or inconclusive verdicts.
mcrt_review_poster — Terra/medium; invoked only after root-session approval, posts exactly approved and re-anchored findings; never approves PRs, resolves threads, or edits code.
Define the orchestrator input/output contract:
Input: repository boundary, review type, optional work-item/PR ID, requested lenses, and hold or explicit approved finding IDs.
Output: selected skill, change map when warranted, criterion verdicts, structured evidence, surviving findings, local uncertainty, worker results, quota state, and resume checkpoint.
Route all flows to the existing toolkit skills. Preserve their lens rules: TypeScript is automatic only when already triggered; maintainability remains opt-in.
Model and quota policy:
Run one worker at a time; use narrow context packets and never repeat completed discovery.
Use Luna only for bounded mechanical discovery; Terra for review work and posting; Sol only for the independent final challenge.
Check authoritative quota signals before each worker, escalation, Sol pass, remote action, and expensive validation.
At seven-day remaining <= 50%, used >= 50%, or ambiguous interpretation, persist a pause checkpoint and stop all model work.
Add deterministic checkpoint and guard utilities for input validation, worker-result schema validation, one active run, approval-set reconciliation, and model-routing audit logs.
Document installation, invocation examples, agent boundaries, approval flow, resume flow, Azure DevOps/Git capability requirements, and the next minor release. Ship this as the toolkit’s next minor version, including changelog, release metadata, generated payload verification, and release checks.
Do not use the Agents SDK as the v1 runtime. Retain an explicit future extension point for an SDK-hosted service if centralized traces, API-based execution, or platform eval datasets become a requirement.
**Test plan:**

Unit-test installer dry-run, idempotency, conflict refusal, nested-agent configuration, checkpoint transitions, approval filtering, quota pauses, and malformed worker results.
Add fixture runs for: clean local task review; missing requirements capability; multi-layer PR; invalid inline anchor; TypeScript and maintainability lens routing; rejected adversarial finding; and attempted unapproved posting.
Run toolkit validation, lint, unit tests, payload build/verification, adapter tests, and a read-only PR dry run against a configured provider.
Require a human-approved pilot posting before enabling documented posting instructions; no automatic posting mode is introduced.

**Assumptions:**
The existing portable skills remain the authoritative review behavior and are not replaced by an Agents SDK application.
The initial delivery is installable from the toolkit and documented only; it is not installed in Aplicatudo or globally as part of this work.
Existing uncommitted toolkit changes are user-owned and excluded from this implementation unless they overlap a necessary version/release edit.
