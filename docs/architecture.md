# Architecture

## The governing decision

This plugin conforms to
[Monolith-INC/agent-plugins-toolkit](https://github.com/Monolith-INC/agent-plugins-toolkit) and does
not deviate from it. Where the template and convenience disagree, the template wins. Everything on
this page follows from that.

## Repository shape

```text
plugins/monolithic-code-review-toolkit/   portable source (hand-authored)
├── plugin.json                           Agent Plugins v1.0.0 manifest
└── skills/<name>/SKILL.md                one self-contained document per skill
        │
        │  scripts/build_payloads.mjs → compileVendorPayload(source, vendor, output)
        ▼
payloads/{claude,cursor,codex}/           generated, gitignored, rebuilt in CI
├── bundle.json                           modes, hashes, adapter identity, digests
└── payload/                              the installable tree for that host
```

The portable root is the single source of truth, and it is the **only** copy of a skill in this
repository. Payloads are build output: gitignored, compiled on demand, and produced fresh at release
time. Committing them would put four byte-identical copies of every `SKILL.md` under version control
to carry eighteen lines of genuinely derived content — the three vendor manifests.

This also matches the template more closely, not less. Upstream, `plugins/hello-world/` contains only
`plugin.json` and `skills/`; payloads live inside the adapter packages that produce them, because
proving adapter determinism is that repository's product. This repository ships no adapters, so
payloads have no home in it.

No `.claude-plugin/`, `.cursor-plugin/`, or `.codex-plugin/` manifest inside a **compiled payload**
is written by hand. Two **repository-level marketplace descriptors** are committed catalog metadata
and are not build output:

- `.cursor-plugin/marketplace.json` — Cursor team-marketplace wiring; `source` must point at the
  portable plugin root in git, not at gitignored `payloads/`.
- `.agents/plugins/marketplace.json` — Codex marketplace wiring with the same portable `source`.

## The pinned toolkit

`@agent-plugins/cli` and `@agent-plugins/core` are **not published to npm** — both 404 on the
registry, and they depend on each other with `workspace:*`. They cannot be added as dependencies.

`scripts/with_toolkit.sh` therefore clones the toolkit at a pinned commit into `.toolkit/`
(gitignored), builds it once, and invokes its CLI. The pin makes validation mean the same thing on
every machine and in CI; bump it deliberately, never automatically.

## The payload allowlist

Every adapter enforces a strict path allowlist. Anything outside it is rejected as `*.payload.path`:

| Vendor | Allowed payload paths                                                                                    |
| ------ | -------------------------------------------------------------------------------------------------------- |
| claude | `.claude-plugin/plugin.json`, `skills/<name>/SKILL.md`, `hooks/hooks.json`, `.mcp.json`                  |
| codex  | `.codex-plugin/plugin.json`, `skills/<name>/SKILL.md`, `hooks/hooks.json`, `.mcp.json`                   |
| cursor | `.cursor-plugin/plugin.json`, `skills/<name>/SKILL.md`, `rules/<id>.mdc`, `hooks/hooks.json`, `mcp.json` |

The compile step maps each skill to its `SKILL.md` body alone. Three consequences shape this project
and are recorded in
[ADR-0001](../AI_Codex/Architecture/ADR/ADR-0001-skill-runtime-under-payload-allowlist.md):

**Skills are self-contained.** Bundled `references/`, `scripts/`, and `assets/` do not travel, even
though Claude Code and Codex both document them for plain skills — the toolkit is stricter than the
hosts it targets. Each `SKILL.md` carries its whole procedure, and `validate_plugin.py` fails the
build if any other file appears in a skill directory.

**There are no commands.** No adapter emits a `commands/` directory. Cursor and Codex support
commands natively, and in Claude Code `commands/` and `skills/` are the same discovery surface, but
none of that is reachable through the template. Skills are the invocation surface everywhere.

**Installation is host-native.** The toolkit's role here is to compile and verify; distribution
belongs to each host. Payloads are released as per-host archives and installed through the host's own
mechanism. For Claude Code that is skills-directory discovery: a folder containing
`.claude-plugin/plugin.json` under `~/.claude/skills/` or `<repo>/.claude/skills/` loads as
`<name>@skills-dir` with no marketplace and no install step — so nothing has to be hand-authored to
make the payload installable. For Cursor, end users run `scripts/install-cursor.sh` (or the
documented one-liner in README) to install the latest release payload into
`~/.cursor/plugins/local/<name>/`; GitHub marketplace installs resolve
`.cursor-plugin/marketplace.json` against the committed portable root.

## What the portable manifest carries

Required `name` and `version`; optional `description`, `schemaVersion`, and `extensions`. This plugin
declares only the first four — `extensions` is opaque, preserved through inspection but never read by
the toolkit or by any host, and adapters strip it from the compiled vendor manifest entirely. Project
metadata that nothing consumes belongs in documentation, not in a manifest where it can silently go
stale.

Hooks and rules do not need vendor files either. The compiler reads them from
`extensions["org.agent-plugins.distribution"]` as `rules[]` (with inline content, activation, and
file globs) and `hookIntents[]` (portable lifecycle and tool-kind declarations), and each adapter
renders them into its native shape. This plugin currently declares neither.

## Requirement sources

No skill names a tracker vendor. `review-setup` resolves whatever a consuming repository uses onto
three capabilities — `fetch_work_item`, `fetch_parent`, `list_linked_artifacts` — and records
concrete tool names or path templates in `.monolithic-code-review/sources.json`. Capabilities that
cannot be satisfied are listed under `unsupported`, and dependent skills report that rather than
inventing requirements.

This keeps tracker choice out of the plugin entirely. Linear appears in this repository's own
`.mcp.json` because it is how *this* project is managed, and in the provider recipes as one example
among several — never as a dependency.

## Project knowledge

Requirement sources answer what a piece of work asked for. They say nothing about what the
repository requires of any change. `discover-project-knowledge` records that separately, as a
deterministic tree under the `knowledge.root` recorded in `sources.json`:

```text
<knowledge.root>/
├── manifest.md      store header: schema version, derived_from_commit, tiers present
├── catalog.tsv      routing table, regenerated from the units so the two cannot disagree
├── 1-identity/      purpose, consumers, ownership          ← asked, never inferred
├── 2-structure/     topology, conventions, domain, architecture
├── 3-mechanics/     stack, dependencies, build, testing, data, contracts, runtime ops
├── 4-rules/         coding standards, workflow, security, budgets  ← asked or quoted
└── 5-evolution/     hotspots, debt, health, risks
```

Three properties make it usable by an agent rather than merely present:

- **Progressive disclosure.** Manifest, then routing table, then unit. Retrieval is a cost ladder —
  `catalog` (~200 tokens) → `find` (~500) → `fetch` (~800) — and no step forces a full-corpus read.
- **Lexical addressing first.** The tree is deterministic, so `catalog.tsv` plus `grep` answers on
  any host. A vector-only path is rejected: it has no verifiable failure mode.
- **Provenance as a trust boundary.** `derived` and `stated` units may be cited as project rules;
  `assumed` units are `INCONCLUSIVE` by construction. This is the same three-state evidence contract
  the reviews already enforce, applied to the store's own claims.

`adapters/knowledge/` serves the same tree over MCP with ranking, backlinks, bounded output and
version-checked writes. It lives outside the plugin because
[ADR-0001](../AI_Codex/Architecture/ADR/ADR-0001-skill-runtime-under-payload-allowlist.md) restricts
a skill directory to `SKILL.md`, and it carries this repository's only third-party Python
dependency. See
[ADR-0006](../AI_Codex/Architecture/ADR/ADR-0006-project-knowledge-store-and-lookup-contract.md).

## Quality lenses

Lifecycle reviews (`review-task`, story pre/post-flight, `review-feature`) stay requirements-first.
Two quality lenses extend them without replacing intent checks. See
[ADR-0002](../AI_Codex/Architecture/ADR/ADR-0002-intent-first-core-and-opt-in-quality-lenses.md)
and the [evidence protocol](../AI_Codex/Architecture/Protocols/review-evidence-and-presentation.md).

`review-setup` detects TypeScript repositories and writes `quality_lenses` into
`.monolithic-code-review/sources.json`:

```json
"quality_lenses": {
  "typescript": "mandatory",
  "maintainability": "off"
}
```

| Lens | Trigger | Skill |
| --- | --- | --- |
| TypeScript | `quality_lenses.typescript: mandatory`, any `.ts`/`.tsx` in the changed scope, or `--lenses typescript` / `--lenses all` | `review-typescript` |
| Maintainability | `--lenses maintainability` / `--lenses all` only; never silent | `review-maintainability` |

When a lens runs inside a lifecycle review, the agent executes the lens skill procedure on the same
changed scope and merges only `VERIFIED` findings into a labeled report subsection. User-invoked
lifecycle skills accept flags in the message, for example:

```text
/monolithic-code-review-toolkit:review-task --lenses maintainability
/monolithic-code-review-toolkit:review-story-postflight --lenses all
```

If a repository already carries `.monolithic-code-review/sources.json` from an older setup run,
rerun `review-setup` after upgrading the toolkit so TypeScript detection and the saved
`quality_lenses` contract reflect the current release.

Post-flight reviews run lens passes before user confirmation so lens findings appear in the approval
table and follow the same write gate as requirements findings.

### Cursor installation

End users install with one command — no repository checkout or manual tarball steps:

```bash
curl -fsSL https://raw.githubusercontent.com/Monolith-INC/monolithic-code-review-toolkit/main/scripts/install-cursor.sh | bash
```

`scripts/install-cursor.sh` resolves the latest GitHub release, downloads the Cursor payload
archive, replaces `~/.cursor/plugins/local/monolithic-code-review-toolkit`, and verifies the
manifest and skill directories. Contributors may alternatively symlink a built payload or register
the repository as a Cursor marketplace (`.cursor-plugin/marketplace.json` points at the committed
portable plugin root).

### Codex installation

Codex supports two valid install paths:

- Git marketplace install: `codex plugin marketplace add Monolith-INC/monolithic-code-review-toolkit`
  followed by `codex plugin add monolithic-code-review-toolkit@monolithic-code-review-toolkit`.
- Release payload install: extract the tagged Codex archive so `.codex-plugin/plugin.json` and
  `skills/` land together under the installed plugin root.

Git marketplace installs show version `local` in `codex plugin list` because the installed source
is a repository checkout, not a packaged archive. Use the release payload when you need the
installed artifact to match a specific published tag exactly.

The optional Codex review-orchestrator companion lives under `adapters/codex/`,
outside the portable plugin root. It installs custom agents and deterministic
checkpoint guards into a trusted Codex scope; placing it in the plugin would
violate the payload allowlist. It coordinates existing review skills
sequentially, uses explicit quota pauses, and leaves all PR posting behind a
root-session approval gate. Its installer uses Python 3.12+, modifies only
managed agent files, and applies a surgical `agents.max_depth` configuration edit.

The optional Claude review-orchestrator companion lives under `adapters/claude/`
and runs the same four workers, with two host-driven differences. Its
orchestrator is a **skill in the main session**, not an agent, because a skill
can call `AskUserQuestion` — so a worker that returns `needs_input` has its
question routed to the user and the answer sent back with `SendMessage`, which
resumes that worker from its transcript instead of stopping the run. And its
approval gate is a `PreToolUse` hook rather than a prompt rule: the poster marks
each comment `[mcrt:<finding-id>]`, and the hook refuses any pull-request write
whose ids are not in a completed checkpoint's `approved_finding_ids`, covering
both MCP tool calls and provider CLI commands. Claude Code caps subagent nesting
at five levels natively, so no depth configuration is needed; the Codex
seven-day quota gate is omitted because Claude Code exposes no authoritative
equivalent signal.

## Why the design is shaped this way

The four review skills differ by scope, not by rigour setting, because the questions genuinely
differ. A task is checked against its own requirements. A story adds cross-task coherence and
readiness for human review. A feature leads with agreement — DoD, goal, out-of-scope — because a
feature that is well-built and wrong is still wrong. And the post-flight review is the only one that
writes, so it is the only one that carries a fact-checking obligation and an approval gate.

Comment handling is split in two deliberately. `triage-pr-comments` analyses and decides nothing;
`respond-pr-comments` acts and analyses nothing. Responding to a review is delicate and hard to take
back, so the judgement and the action are kept apart with the user in between.
