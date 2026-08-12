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
payloads/{claude,cursor,codex}/           generated (never hand-edited)
├── bundle.json                           file bytes, modes, hashes, adapter identity, digests
└── payload/                              the installable tree for that host
```

The portable root is the single source of truth. Vendor payloads are derived from it by the
toolkit's own adapters, so no `.claude-plugin/`, `.cursor-plugin/`, or `.codex-plugin/` file in this
repository is written by hand.

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
make the payload installable.

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

## Why the design is shaped this way

The four review skills differ by scope, not by rigour setting, because the questions genuinely
differ. A task is checked against its own requirements. A story adds cross-task coherence and
readiness for human review. A feature leads with agreement — DoD, goal, out-of-scope — because a
feature that is well-built and wrong is still wrong. And the post-flight review is the only one that
writes, so it is the only one that carries a fact-checking obligation and an approval gate.

Comment handling is split in two deliberately. `triage-pr-comments` analyses and decides nothing;
`respond-pr-comments` acts and analyses nothing. Responding to a review is delicate and hard to take
back, so the judgement and the action are kept apart with the user in between.
