# Changelog

All notable changes to `monolithic-code-review-toolkit` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-08-27

### Added

- A distributable Claude Code review-orchestrator companion adapter under
  `adapters/claude/`, running the same four workers as the Codex adapter:
  discovery, lifecycle validation, one independent adversarial pass, and
  approved-only posting.
- An orchestrator that is a **skill in the main session** rather than an agent,
  so a worker returning `needs_input` has its questions routed to the user via
  `AskUserQuestion` and the answers sent back with `SendMessage`, resuming that
  worker from its transcript instead of stopping the run.
- A `PreToolUse` poster guard that enforces the approval gate rather than
  requesting it: pull-request writes carry an `[mcrt:<finding-id>]` marker, and
  the hook refuses any whose ids are not in a completed checkpoint's
  `approved_finding_ids`. It covers MCP tool calls and provider CLI commands
  alike, and stays inert when no run is in flight so manual comments are
  unaffected.
- An idempotent safe installer with `--scope`, `--dry-run`, `--uninstall`,
  repeatable `--scm-tool` for MCP-based providers, and a surgical `settings.json`
  edit that preserves unrelated keys and other hooks.

### Changed

- Document the Claude adapter's two host-driven divergences from Codex: no
  `max_depth` configuration, because Claude Code caps subagent nesting at five
  levels natively; and no seven-day quota gate, because Claude Code exposes no
  authoritative equivalent signal.

## [0.3.0] - 2026-08-27

### Added

- A distributable Codex review-orchestrator companion adapter with isolated
  discovery, lifecycle-review, adversarial, and approved-only posting agents.
- Deterministic review input, worker-result, checkpoint, approval, and
  authoritative seven-day quota guards, plus an idempotent safe installer.

### Changed

- Document Codex multi-agent review installation and its portable-payload
  boundary. The adapter is documented only and is not installed in a consumer
  repository by this release.

## [0.2.5] - 2026-08-27

### Changed

- Clarify Codex installation guidance: Git marketplace installs are valid, but `codex plugin list`
  reports the installed version as `local`; the release payload remains the immutable install path
  when users want an explicit tagged artifact.
- Document that repositories carrying older or stale `.monolithic-code-review/sources.json` files
  should rerun `review-setup` after upgrading when TypeScript detection was previously recorded as
  `off` for a TypeScript monorepo.

## [0.2.4] - 2026-08-27

### Fixed

- Align the standalone `review-typescript` skill text with the accepted automatic trigger contract:
  lifecycle reviews invoke it when `quality_lenses.typescript` is `mandatory`, when the changed
  scope includes `.ts` or `.tsx`, or when `--lenses typescript|all` is requested.

### Added

- A repository test that guards the accepted TypeScript-lens lifecycle trigger contract in
  `skills/review-typescript/SKILL.md`.

## [0.2.3] - 2026-08-27

### Added

- `scripts/install-cursor.sh` — one-command Cursor install from the latest GitHub release (full
  payload: manifest, skills, and all shipped capabilities).

### Changed

- README **Cursor** section is a single curl pipe; manual tarball, symlink, and marketplace paths
  moved to `docs/architecture.md`.
- Document quality lenses and Cursor install in `docs/architecture.md`, `docs/quality-gates.md`, and
  `CONTRIBUTING.md`.

## [0.2.2] - 2026-08-27

### Added

- `--lenses maintainability|typescript|all` flags on lifecycle review skills for optional quality
  lens passes.
- `quality_lenses` configuration in `review-setup` with automatic TypeScript detection.

### Changed

- TypeScript quality lens runs automatically during lifecycle reviews for TypeScript repositories
  or when the diff includes `.ts`/`.tsx` files.
- Maintainability lens remains flag-gated; agents can invoke both lenses from lifecycle reviews or
  standalone.

## [0.2.1] - 2026-08-27

### Fixed

- Point Cursor marketplace `source` at the committed portable plugin root instead of gitignored
  build output so `/add-plugin` works from a fresh GitHub clone.
- Document the canonical Cursor install path (`~/.cursor/plugins/local/`) and tarball extraction
  command.

### Changed

- Validate `.cursor-plugin/marketplace.json` in `lint:plugin` to prevent gitignored marketplace
  sources from shipping again.

## [0.2.0] - 2026-08-27

### Added

- Three-state evidence verdicts and conditional attention-ordered change maps in lifecycle reviews.
- `prepare-pr-for-review`, `review-maintainability`, and `review-typescript` as explicitly invoked,
  read-only skills.
- An optional, explicitly requested bounded-remediation mode for `respond-pr-comments`.

### Changed

- Review findings now report only verified claims; disproved claims are dropped and inaccessible
  evidence remains local uncertainty.

## [0.1.1] - 2026-08-12

### Changed

- Configure the pull-request provider per repository through an SCM capability map. Setup no longer
  stops on non-GitHub origins, and PR-facing skills execute the recorded provider mappings instead
  of assuming `gh`. Includes GitHub and Azure DevOps setup recipes.

### Fixed

- Add the repository-level Codex marketplace descriptor required by
  `codex plugin marketplace add`.
- Clarify that per-host payload archives are generated at release time and are not committed to
  the repository.

## [0.1.0] - 2026-08-12

First release. Seven code review skills covering the work lifecycle, compiled for Claude Code,
Cursor, and Codex.

### Added

- **`review-setup`** — one-time per-repository configuration. Detects the pull-request host from
  `origin`, enumerates whatever requirement source is actually available, maps it onto a
  three-capability contract with user confirmation, and persists
  `.monolithic-code-review/sources.json`. Ships provider recipes for Linear, Jira, Azure DevOps,
  YouTrack, GitHub issues, and file-backed vaults as examples rather than dependencies.
- **`review-task`** — reviews a completed unit of work against its task requirements. Read-only.
- **`review-story-preflight`** — reviews the whole story branch before a pull request exists,
  including cross-task contradictions, leftovers, and verification evidence. Ends with an explicit
  ready-or-blocked verdict.
- **`review-story-postflight`** — adversarial review of the remote pull request diff. Classifies
  findings as `error`, `gap`, `improvement`, or `off-scope`, fact-checks each against current
  official documentation and the story's own artifacts, drops what does not survive, and posts
  categorized comments after user approval.
- **`review-feature`** — the strictest gate. Judges agreement with the definition of done, goal, and
  out-of-scope instructions before considering code quality, and reports scoped-but-undelivered work.
- **`triage-pr-comments`** — enumerates every unresolved review thread with file and line,
  fact-checks each comment adversarially, and assigns four independent attributes: fact-check
  (`true`/`false`), suggestion (accept/decline), risk (`high`/`medium`/`low`), and justification.
  Presents a canvas for decision-making. Decides nothing itself.
- **`respond-pr-comments`** — posts replies and applies accepted changes, only under explicit user
  instruction. Never resolves, dismisses, or approves a thread.
- Portable Agent Plugins v1.0.0 plugin root with compiled payloads for claude, cursor, and codex.
- `scripts/with_toolkit.sh` — pinned, reproducible toolkit checkout and build.
- `scripts/build_payloads.mjs` — adapter-driven payload compilation and drift verification.
- `scripts/validate_plugin.py` — version lockstep, portable frontmatter contract, and a guard
  against content the adapter allowlist would silently drop.
- CI across ubuntu, macOS, and Windows, plus a template-conformance job that builds the pinned
  toolkit and runs its own validator against this plugin.
- Release workflow producing one payload archive per host.

### Notes

Recorded in
[ADR-0001](AI_Codex/Architecture/ADR/ADR-0001-skill-runtime-under-payload-allowlist.md) and revisited
after this release:

- Vendor adapters ship `SKILL.md` and nothing else, so skills are fully self-contained. Diff parsing
  and pull-request comment line-anchoring are performed by the agent rather than by tested helper
  code — the acknowledged weak point of this release.
- No adapter emits a `commands/` directory, so there is no slash-command surface on any host.
- Installation is host-native: payloads ship as per-host archives and load through each host's own
  mechanism.

[Unreleased]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.2.5...v0.3.0
[0.2.5]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/releases/tag/v0.1.0
