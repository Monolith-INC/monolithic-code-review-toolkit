---
title: Codex review orchestrator implementation plan
type: implementation-plan
status: implemented-locally
created: 2026-08-27
---

# Codex review orchestrator implementation plan

## Objective

Add a distributable Codex companion adapter that coordinates all existing
requirements-first review skills through isolated, sequential workers and never
posts a PR comment without a root-session approval.

## Decisions

- Keep portable review skills authoritative; the adapter is host-specific and
  lives outside the payload allowlist.
- Ship five roles: orchestrator, bounded discovery, lifecycle validator,
  independent adversarial reviewer, and approved-only poster.
- Route Luna/medium only to bounded discovery, Terra/medium to ordinary review
  and posting, and Sol/high once to the final independent challenge.
- Treat authoritative seven-day remaining `<= 50`, used `>= 50`, and ambiguous
  signals as hard pauses. Do not downgrade models to bypass a pause.
- Deliver an installer and documentation only. Do not install into Aplicatudo
  or user scope during this implementation.
- Do not use an Agents SDK runtime in v1; preserve the guard/checkpoint contract
  as a future service boundary.

## Acceptance criteria

- Installer supports user/project scope, dry-run, idempotent install, conflict
  refusal, and safe uninstall while requiring `agents.max_depth >= 2`.
- Guard utility validates routing, worker results, one active checkpoint,
  approval sets, and quota pauses deterministically.
- Worker configurations prohibit unapproved posting, source edits, PR approval,
  and thread resolution.
- Documentation covers install, invocation, safety boundaries, resume state,
  and SCM capability prerequisites.
- Focused adapter tests and existing plugin quality gates pass before release.
