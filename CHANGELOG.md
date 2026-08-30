# Changelog

All notable changes to `monolithic-code-review-toolkit` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Knowledge retrieval evaluation** (`pnpm eval:knowledge`). The store shipped in 0.5.0 with every
  design choice justified by argument and none by evidence. Tier 1 measures ranking deterministically
  — rank@1/@3, mean reciprocal rank, ladder token cost, and the margin between a correct unit and a
  planted near-miss — against a committed baseline, over a 23-unit synthetic fixture and twelve
  questions. Four assertions are pass/fail: a links-only unit stays unreachable by search, an
  `assumed` unit announces itself, an over-budget fetch truncates with a handle that advances, and
  ordering is reproducible.
- Tier 2 (`adapters/knowledge/eval/model_eval.md`) is a documented, hand-run procedure for the two
  metrics that are judgements rather than computations: hit@1 on the **pick**, and the
  wrong-file-confidence rate. `MCRT-001` had demanded both of those *and* that the harness need no
  model; that contradiction is recorded and corrected in the ticket rather than quietly resolved.

### Changed

- The eval reports two real retrieval weaknesses rather than tuning them away. "Which layer owns
  currency rounding" ranks the architecture unit above the rules unit that states the rule, and a
  short identity unit outranks operations for a gateway retry question. Both carry a negative
  distractor margin in the baseline. A baseline of 1.0 measures nothing.
- The harness's own sensitivity is measured: of five deliberate ranking perturbations three are
  caught and two are not, and the aggregates alone missed two of the three — they were caught by the
  per-question rank comparison and the distractor margin, both added because the sweep showed they
  were needed.

## [0.5.0] - 2026-08-30

### Added

- **Project knowledge.** Reviews could measure a diff against its work item but
  had no source for what the *project* requires of any change: no skill read
  `CLAUDE.md`, a contributing guide, an ADR index, or an architecture document,
  and the only project fact recorded was whether the repository was TypeScript.
  `discover-project-knowledge` now indexes a repository into a file-shaped store
  across five tiers — identity, structure, mechanics, rules, evolution — as
  Markdown units with YAML frontmatter plus TSV for uniform records.
- Every unit records a `provenance`. `derived` facts were read out of the tree
  and name their sources; `stated` facts were authored by a human; `assumed`
  facts are inferred and are `INCONCLUSIVE` by construction, so a review can
  never report an inferred convention as a project rule. Discovery derives the
  machine-derivable tiers and **asks** about purpose, ownership and the
  rationale behind rules, because those are the ones worth recording and the
  ones a machine cannot establish.
- Incremental refresh. Units name the repository paths they were derived from,
  so a refresh re-derives only the units whose inputs actually moved, and never
  overwrites a human-authored unit without asking.
- `adapters/knowledge/` — an optional MCP server exposing the store through four
  read tools and three write tools. The read side is a stated cost ladder
  (`knowledge_catalog` → `knowledge_find` → `knowledge_fetch`); hits carry
  `matched_terms` so a bad query is self-diagnosable; empty results return the
  facet values and near-miss terms that do exist; a version conflict returns the
  current content and a failed patch returns the surrounding text, so a retry
  happens in the same turn; output is bounded with an explicit continuation
  handle; ordering is deterministic.

### Changed

- `review-setup` asks where the store should live — per-developer, committed and
  shared with the team, or inside an existing vault — and records the choice as
  `knowledge.root`. It then runs discovery.
- All nine non-setup skills consult the store. The four lifecycle reviews share
  one "Project knowledge" section; the quality lenses, PR preparation, comment
  triage and comment response each reach for the tiers they actually need.
  Project knowledge is evidence for a finding, never a finding generator: a unit
  raises one only when its provenance permits and the changed lines contradict
  it, and the finding cites the unit id.
- The store is reachable without the adapter. Its layout is deterministic, so
  `catalog.tsv` plus `grep` satisfies the same ladder — lexical addressing first
  is a design requirement, not a degradation.
- Read-only skills say explicitly that reading the store is not a mutation, and
  hold no write tools.
- `review-typescript` gets the narrowest slice on purpose: stack facts freely,
  but a coding standard only where a human authored it, so the lens cannot drift
  back into the rubric-copying it forbids.

### Fixed

- `review-setup` now writes `conventions.language` and
  `conventions.requirement_headings`. The Claude adapter's validator, adversarial
  and poster workers have read both since 0.4.0 — to choose the language a
  posted comment is written in, and to avoid assuming English requirement
  headings — and neither key was ever produced.

## [0.4.2] - 2026-08-27

### Fixed

- `--scm-read-tool` now also reaches `mcrt-review-adversarial`. The challenge
  pass fact-checks findings whose premises are tracker criteria and pull-request
  scope statements, and it held no provider tool, so it could not open the source
  it was checking. Found by a real run: it declared the gap honestly and reached
  its conclusion by another route, but inference is not verification.

### Changed

- The validator now weighs an explicit out-of-scope statement — in the pull
  request description, work-item comments, or a plan document — against a
  tracker criterion, and reports the disagreement as tracker drift in
  `local_uncertainty` rather than as a finding against the author. Holding a
  diff to a requirement the team has already superseded is correct about the
  text and wrong about the work.
- The adversarial worker is told to read primary sources where it holds the
  tools, and to treat an unverifiable premise as grounds for `inconclusive`.

## [0.4.1] - 2026-08-27

Packaging and CI only. No change to any shipped adapter, skill, or plugin file;
0.4.0's runtime and 0.4.1's are identical.

### Fixed

- The Codex and Claude orchestrator archives no longer carry compiled bytecode.
  The release job runs the adapter tests before packaging, so importing those
  modules leaves `__pycache__` behind, and `tar` does not honour `.gitignore` —
  0.4.0 shipped 7 stray `.pyc` files in the Codex archive and 9 in the Claude
  one, roughly doubling it. Each archive now matches its tracked tree exactly.
  The bytecode was inert, so 0.4.0 remains usable; 0.4.1 is simply clean.

### Changed

- The CI matrix drops `windows-latest`. Windows is not a shipping target, so
  testing it bought nothing and cost a red build on line-ending assertions.
  `docs/quality-gates.md` claimed three platforms and now says two.


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
- An idempotent safe installer with `--scope`, `--dry-run`, `--uninstall`, and a
  surgical `settings.json` edit that preserves unrelated keys and other hooks.
- Separate provider-tool flags: `--scm-tool` grants the poster its write
  capability, and `--scm-read-tool` grants `discovery` and `validator` read-only
  provider access. They are distinct so a write tool can never reach a worker
  whose job is to look. Without read tools those workers verify only
  shell-reachable capabilities and report MCP-based ones as unverified rather
  than inferring success from an adjacent check.

- Provider-call discipline on every worker that can reach a provider: targeted reads only, one
  attempt, never re-authenticate, never echo credentials, and treat a missing tool as a finding
  rather than a reason to take another route. Retrying an OAuth-backed MCP server strands
  processes waiting on callbacks nobody completes.

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

[Unreleased]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/Monolith-INC/monolithic-code-review-toolkit/compare/v0.4.0...v0.4.1
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
