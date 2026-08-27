# Monolithic Code Review Toolkit — Product Requirements

**Status:** accepted baseline; current release: 0.4.2
**Version:** 0.1.0 (baseline)
**Date:** 2026-08-12
**Source brief:** `instructions.md`

## Version history

- **0.4.0** — Add the optional Claude Code review-orchestrator companion adapter: the same four
  workers, with the orchestrator as a main-session skill so worker questions reach the user and
  the answers return to the worker, and with the approval gate enforced by a `PreToolUse` hook.
- **0.3.0** — Add the optional Codex review-orchestrator companion adapter: isolated sequential
  workers, explicit approval-gated posting, deterministic checkpoints, and authoritative quota
  pauses. The portable review skills remain authoritative and the adapter is not installed into a
  consumer repository by default.
- **0.2.5** — Clarify Codex repository-vs-release installation behavior and document rerunning
  `review-setup` when a stale repository-local `sources.json` still records TypeScript monorepos as
  `quality_lenses.typescript: off`.
- **0.2.4** — Clarify the accepted automatic TypeScript lens trigger contract in the standalone
  skill and lock it with a repository test.
- **0.2.3** — One-command Cursor install via `scripts/install-cursor.sh`; README Cursor section
  simplified to a single curl pipe.
- **0.2.2** — Mandatory TypeScript lens in lifecycle reviews for TS repos and `.ts`/`.tsx` diffs;
  `--lenses` flags for maintainability and TypeScript on lifecycle skills.
- **0.2.1** — Cursor marketplace and install documentation fix. Marketplace `source` now
  points at the committed portable plugin root; install docs name `~/.cursor/plugins/local/`.
- **0.2.0** — Additive release: a three-state evidence contract, conditional
  attention-ordered change maps, read-only PR preparation, explicit maintainability and TypeScript
  lenses, and bounded user-directed remediation. The accepted 0.1.0 product scope remains intact.
- **0.1.1** — Follow-up maintenance release. Configured pull-request providers per repository and
  added the repository-level Codex marketplace descriptor. The accepted 0.1.0 product scope is
  unchanged.

## Goal

Give an agent a defined review procedure for each stage of the work lifecycle, so that what gets
reviewed is measured against **what the work was actually asked to do** — not against generic code
quality. The unit of judgement is agreement with requirements, description, and definition of done.

## Scope

Four lifecycle stages plus quality lenses and PR preparation, delivered as ten skills:

| Stage / mode                              | Skill                     |
| ----------------------------------------- | ------------------------- |
| Configuration (once per repository)       | `review-setup`            |
| Task done                                 | `review-task`             |
| User story done — pre-flight              | `review-story-preflight`  |
| User story done — post-flight             | `review-story-postflight` |
| Feature done                              | `review-feature`          |
| Reviewer comments received                | `triage-pr-comments`      |
| Responding to reviewer comments           | `respond-pr-comments`     |
| Pull request preparation (explicit)       | `prepare-pr-for-review`   |
| Maintainability lens (flag or standalone) | `review-maintainability`  |
| TypeScript lens (auto, flag, or standalone) | `review-typescript`     |

Lifecycle reviews accept optional `--lenses maintainability|typescript|all` flags. The TypeScript
lens also runs automatically when `review-setup` marks the repository as TypeScript or the changed
scope includes `.ts`/`.tsx` files. See [architecture](../architecture.md#quality-lenses).

## Out of scope for v0.1.0

- Shipping a hard-coded dependency on one SCM vendor.
- Naming or depending on a specific work-tracker vendor.
- Executable helper code shipped inside the plugin — see
  [ADR-0001](../../AI_Codex/Architecture/ADR/ADR-0001-skill-runtime-under-payload-allowlist.md).
- Slash commands. No vendor adapter emits a `commands/` directory.
- Approving or requesting changes on a pull request. The toolkit comments; humans decide.
- Resolving or dismissing review threads.

## Cross-cutting requirements

**R1 — Comment contract.** Every finding, in every skill, in every medium, is
**what was found → what are the consequences → what is suggested**. Compact. Posted pull-request
comments tag the author unless the user declines.

**R2 — Categories.** Findings are classified `error`, `gap`, `improvement`, or `off-scope`.
`improvement` is admitted only when tied to the work item's own goal, never as general code polish.

**R3 — Severity.** `critical`, `high`, `medium`, `low`, applied consistently across skills.

**R4 — No invented requirements.** When the requirement source cannot be reached, the skill says so
and asks. It never substitutes its own judgement of what the work should have done.

**R5 — Tracker independence.** No skill names a tracker vendor. All requirement access goes through
the three-capability contract resolved by `review-setup`.

**R5a — SCM independence.** The pull-request provider is selected and configured per repository.
PR-side skills use the SCM capability mappings written by `review-setup`, never a globally assumed
provider.

**R6 — Template conformance.** The plugin is a portable Agent Plugins v1.0.0 root that passes
`agent-plugin validate` and `inspect` with zero diagnostics, and compiles to all three vendor
payloads. No hand-authored vendor files.

**R7 — Write actions are gated.** No skill posts to a pull request or modifies code without explicit
user instruction for that specific action.

## The capability contract

`review-setup` resolves whatever the consuming repository uses onto three requirement capabilities:

| Capability                  | Returns                                                     |
| --------------------------- | ----------------------------------------------------------- |
| `fetch_work_item(id)`       | title, description, requirements, acceptance criteria / DoD |
| `fetch_parent(id)`          | parent item — task → story, story → feature                 |
| `list_linked_artifacts(id)` | specs, design documents, attachments, linked URLs           |

Unsatisfiable capabilities are recorded in `unsupported` so dependent skills degrade honestly.
It separately resolves the repository's PR provider onto SCM capabilities for PR metadata, diffs,
threads, conversation comments, inline and summary comments, and thread replies. Those mappings are
stored per repository under `scm.capabilities`.

## Feature / user story / task breakdown

Tracked in Linear on team **AGE**: project = this plugin, milestone = feature, issue = user story,
sub-issue = task.

### F1 — Template-conformant plugin foundation

**Goal:** a plugin root that provably does not deviate from the template.
**DoD:** `agent-plugin validate` returns `{"ok":true}`; `inspect` lists every skill with zero
diagnostics; all three vendor payloads compile and verify; CI enforces all of it.

- **US1.1** Portable plugin root — manifest with `schemaVersion`, skills as immediate children of `skills/`.
- **US1.2** Pinned toolkit integration — reproducible checkout, build, and CLI invocation.
- **US1.3** Vendor payload compilation and drift verification for claude, cursor, codex.
- **US1.4** Repository invariant validation — version lockstep, portable frontmatter,
  unshippable-content guard — with unit tests and CI.

### F2 — Requirement source resolution

**Goal:** the toolkit works against any tracker without naming one.
**DoD:** `review-setup` resolves all three capabilities against at least one real source, records
`unsupported` for the rest, verifies by fetching one real work item, and persists the result.

- **US2.1** Capability contract definition and `sources.json` schema.
- **US2.2** `review-setup` interview, detection, confirmation, and verification.
- **US2.3** Provider recipes for the common trackers, as examples rather than dependencies.
- **US2.4** Per-repository SCM provider detection and capability mapping.

### F3 — Lifecycle review skills

**Goal:** review at task, story pre-flight, and feature scope against documented intent.
**DoD:** each skill gives every requirement and DoD item an explicit verdict, reports findings in the
R1 contract, names off-scope work, and states what it could not verify.

- **US3.1** `review-task` — smallest unit, report only.
- **US3.2** `review-story-preflight` — whole-branch, cross-task coherence, leftovers, ready/blocked verdict.
- **US3.3** `review-feature` — agreement before quality; DoD, goal, and out-of-scope first.

### F4 — Adversarial pull request review

**Goal:** an adversarial review of the remote diff whose findings survive verification.
**DoD:** findings fact-checked against current official documentation and story artifacts; unverified
findings dropped and counted; inline comments anchored to lines the diff changes; nothing posted
without user approval.

- **US4.1** `review-story-postflight` — ingest, four-category scan, fact-check, confirm, post.
- **US4.2** Line-anchoring procedure, with summary-comment fallback when an anchor is uncertain.

### F5 — Reviewer comment handling

**Goal:** treat human review comments as claims to be tested, and act only on instruction.
**DoD:** every unresolved thread listed once with file and line and all four attributes; canvas plus
terminal summary; `respond-pr-comments` performs no action without an explicit instruction.

- **US5.1** `triage-pr-comments` — enumerate, fact-check, assign fact-check/suggestion/risk/justification.
- **US5.2** Canvas presentation for decision-making.
- **US5.3** `respond-pr-comments` — user-gated replies and code changes; never resolves a thread.

### F6 — Documentation and release

**Goal:** installable and comprehensible.
**DoD:** README with badges and install instructions per host; CHANGELOG following Keep a Changelog;
ADRs recorded; `_reference/` removed; v0.1.0 tagged and released with per-host payload archives.

- **US6.1** README, architecture and quality-gate documentation.
- **US6.2** CHANGELOG and release workflow.
- **US6.3** v0.1.0 release with claude, cursor, and codex archives.

## Acceptance for v0.1.0

1. `pnpm validate`, `pnpm inspect`, `pnpm payloads:verify`, `pnpm lint:plugin`, `pnpm test` all pass.
2. Seven skills discovered by the toolkit with zero diagnostics.
3. Three vendor payloads compiled, verified, and released as per-host archives. Payloads are
   generated build output and are not committed; see [the quality gates](../quality-gates.md).
4. `review-setup` verified end to end against a real work item.
5. A real pull request reviewed by `review-story-postflight` with comments landing on correct lines.
6. `respond-pr-comments` performs no action absent an explicit instruction.

## Acceptance for v0.2.0

1. All v0.1.0 acceptance criteria remain satisfied.
2. Ten skills discovered by the toolkit with zero diagnostics.
3. Lifecycle review skills share the three-state evidence verdict contract; only `VERIFIED` claims
   become findings and `INCONCLUSIVE` claims remain local uncertainty.
4. Story and feature reviews include conditional attention-ordered change maps; `review-task`
   includes the same map only for multi-responsibility diffs.
5. `prepare-pr-for-review`, `review-maintainability`, and `review-typescript` are explicitly
   invoked, read-only skills with self-contained `SKILL.md` payloads.
6. `respond-pr-comments` bounded remediation requires named targets, a positive maximum, and verified
   closure evidence before success.

## Acceptance for v0.2.2

1. All v0.2.0 acceptance criteria remain satisfied.
2. `review-setup` writes `quality_lenses` with TypeScript detection (`mandatory` or `off`) and
   `maintainability: off`.
3. Lifecycle review skills accept `--lenses maintainability|typescript|all` and document the flags in
   their skill descriptions.
4. The TypeScript lens runs automatically during lifecycle reviews when `quality_lenses.typescript`
   is `mandatory` or the changed scope includes `.ts`/`.tsx` files.
5. The maintainability lens runs only when flagged or invoked standalone; post-flight runs lens
   passes before user confirmation.

## Known limitations

Recorded rather than hidden, and revisited after v0.1.0:

- Diff hunk parsing and comment line-anchoring are performed by the agent, not by tested code.
  This is the weak point of ADR-0001 and the reason it carries a revisit trigger.
- No slash-command surface on any host; skills are the only invocation surface.
