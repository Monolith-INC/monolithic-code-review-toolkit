# Monolithic Code Review Toolkit

[![CI](https://github.com/Monolith-INC/monolithic-code-review-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/Monolith-INC/monolithic-code-review-toolkit/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Monolith-INC/monolithic-code-review-toolkit?sort=semver)](https://github.com/Monolith-INC/monolithic-code-review-toolkit/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Agent Plugins](https://img.shields.io/badge/Agent%20Plugins-v1.0.0-8A2BE2)](https://github.com/Monolith-INC/agent-plugins-toolkit)
[![Node](https://img.shields.io/badge/node-%E2%89%A522-brightgreen)](https://nodejs.org)
[![Hosts](https://img.shields.io/badge/hosts-claude%20%7C%20cursor%20%7C%20codex-informational)](#install)

Code review skills for every stage of the work lifecycle — reviewing changes against **what the work
was actually asked to do**, not against generic code quality.

Most review tooling answers "is this code good?". This answers "does this diff agree with its
requirements, its description, and its definition of done?" — and treats off-scope work, unmet
acceptance criteria, and silently dropped scope as findings in their own right.

## Skills

| Lifecycle stage                 | Skill                     | What it does                                                                            |
| ------------------------------- | ------------------------- | ---------------------------------------------------------------------------------------- |
| Configure (once per repo)       | `review-setup`            | Records where requirements and pull requests live                                          |
| Task done                       | `review-task`             | Diff vs task requirements; reports, changes nothing                                        |
| Story done — before the PR      | `review-story-preflight`  | Whole branch vs story DoD; ends with a ready/blocked verdict                                |
| Story done — after the PR       | `review-story-postflight` | Adversarial review of the remote diff; posts fact-checked comments                          |
| Feature done                    | `review-feature`          | Agreement with goal, DoD and out-of-scope first; code quality second                        |
| Reviewers commented             | `triage-pr-comments`       | Fact-checks every comment; presents a canvas for your decision                             |
| Answering reviewers             | `respond-pr-comments`     | Posts replies and applies fixes — only on your explicit instruction                         |
| PR preparation                  | `prepare-pr-for-review`   | Read-only reviewer map, evidence inventory, and gated cleanup proposals                    |
| Explicit quality lens           | `review-maintainability`  | Read-only changed-scope structural review                                                    |
| Explicit quality lens           | `review-typescript`       | Read-only changed-scope TypeScript boundary and invariant review                             |

Skills are namespaced by plugin, so `review-task` is invoked as
`/monolithic-code-review-toolkit:review-task`.

## How findings are reported

Every finding, in every skill, in every medium, follows one contract:

> **Found** — what is there, with `file:line`
> **Consequence** — what it costs or breaks, concretely
> **Suggested** — the specific action to take

Findings are classified `error`, `gap`, `improvement`, or `off-scope`, at severity `critical`,
`high`, `medium`, or `low`. `improvement` is admitted only when tied to the work item's own goal —
never as general code polish.

Three rules keep the output honest:

- **No invented requirements.** When the requirement source is unreachable, the skill says so and
  asks. It never substitutes its own idea of what the work should have done.
- **No manufactured findings.** A clean diff produces a one-line clean report.
- **Nothing is written without permission.** No skill posts a comment or edits code without an
  explicit instruction for that specific action.

Material review claims use an evidence verdict: `VERIFIED` claims may be reported, `NOT VERIFIED`
claims are dropped, and `INCONCLUSIVE` claims remain local uncertainty rather than softened into a
finding. Detailed findings remain ordered by severity; larger changes may first include a concise
map of core behavior, wiring, and mechanical/generated work.

## Install

Each host gets its own compiled payload. Download the archive for your host from the
[latest release](https://github.com/Monolith-INC/monolithic-code-review-toolkit/releases).

### Claude Code

Extract the payload into a skills directory. Claude Code discovers any folder there containing
`.claude-plugin/plugin.json` as a plugin — no marketplace, no install step.

```bash
mkdir -p ~/.claude/skills/monolithic-code-review-toolkit
tar -xzf monolithic-code-review-toolkit-0.2.1-claude.tar.gz \
  --strip-components=1 -C ~/.claude/skills/monolithic-code-review-toolkit payload
```

Restart Claude Code, or run `/reload-plugins`. The plugin loads as
`monolithic-code-review-toolkit@skills-dir`. Use `~/.claude/skills/` for personal scope, or
`<repo>/.claude/skills/` to share it with collaborators through version control.

### Cursor

Extract the payload into Cursor's local plugin directory:

```bash
mkdir -p ~/.cursor/plugins/local/monolithic-code-review-toolkit
tar -xzf monolithic-code-review-toolkit-0.2.1-cursor.tar.gz \
  --strip-components=1 -C ~/.cursor/plugins/local/monolithic-code-review-toolkit payload
```

Reload Cursor (**Developer: Reload Window**). The plugin appears under **Customize**.

For a local checkout, build the Cursor payload and symlink it:

```bash
pnpm payloads:build
ln -s "$(pwd)/payloads/cursor/payload" ~/.cursor/plugins/local/monolithic-code-review-toolkit
```

Or symlink the portable source directly (no build step): `plugins/monolithic-code-review-toolkit`.

Install this repository as a Cursor marketplace, then enable the plugin from **Customize**:

```text
/add-plugin https://github.com/Monolith-INC/monolithic-code-review-toolkit
```

The marketplace manifest points at the committed portable plugin root, not gitignored build output.
For a local checkout, use the repository path instead of the GitHub URL.

### Codex

Install the repository as a marketplace, then install the plugin from it:

```bash
codex plugin marketplace add Monolith-INC/monolithic-code-review-toolkit
codex plugin add monolithic-code-review-toolkit@monolithic-code-review-toolkit
```

For a local checkout, replace the GitHub repository in the first command with its local path.

Alternatively, install from the compiled release payload:

```bash
tar -xzf monolithic-code-review-toolkit-0.2.1-codex.tar.gz
```

The extracted `payload/` contains `.codex-plugin/plugin.json` and `skills/`. Codex also reads the
portable Agent Plugins v1.0.0 manifest directly, so `plugins/monolithic-code-review-toolkit/` from
this repository loads as-is.

### First run

Run `review-setup` once per repository before anything else. It asks where your requirements live,
detects your pull-request host, and writes `.monolithic-code-review/sources.json`.

## Requirement sources

The toolkit names no tracker vendor. `review-setup` maps whatever your repository already uses onto
three capabilities:

| Capability                  | Returns                                                     |
| --------------------------- | ------------------------------------------------------------ |
| `fetch_work_item(id)`       | title, description, requirements, acceptance criteria / DoD   |
| `fetch_parent(id)`          | parent item — task → story, story → feature                   |
| `list_linked_artifacts(id)` | specs, design documents, attachments, linked URLs             |

Worked recipes ship for Linear, Jira, Azure DevOps, YouTrack, GitHub issues, and plain files in a
repository — as examples, not dependencies. An unlisted tracker works as long as those three
capabilities resolve to something. Capabilities a source cannot answer are recorded as `unsupported`
so dependent skills degrade honestly rather than guessing.

**Pull requests** are provider-configured per repository. `review-setup` maps the detected host onto
SCM capabilities in `sources.json`; later skills use those mappings instead of assuming GitHub.
GitHub and Azure DevOps are documented recipes, and other providers can be used when their tooling
satisfies the same capability contract.

## Architecture

The plugin is a portable **Agent Plugins v1.0.0** root that conforms to
[Monolith-INC/agent-plugins-toolkit](https://github.com/Monolith-INC/agent-plugins-toolkit). That
template is the governing architectural decision and is not deviated from.

```text
plugins/monolithic-code-review-toolkit/   portable source — the only hand-authored plugin content
        ↓  toolkit adapter compile
payloads/{claude,cursor,codex}/           generated, verified in CI, never hand-edited
```

No vendor manifest is hand-written. Every `.claude-plugin/`, `.cursor-plugin/`, and `.codex-plugin/`
file in this repository is build output.

Two consequences worth knowing before contributing, both documented in
[ADR-0001](AI_Codex/Architecture/ADR/ADR-0001-skill-runtime-under-payload-allowlist.md):

- **Skills are self-contained.** Adapters ship `SKILL.md` and nothing else, so there are no bundled
  `references/`, `scripts/`, or `assets/`.
- **There are no slash commands.** No adapter emits a `commands/` directory. Skills are the
  invocation surface on all three hosts.

See [docs/architecture.md](docs/architecture.md) for the full picture and
[docs/specs/product-requirements.md](docs/specs/product-requirements.md) for the specification.

## Development

Requires git, Node.js ≥ 22, and Python 3.10+. The first toolkit-backed command clones and builds the
pinned toolkit into `.toolkit/` and takes about a minute; later runs reuse it.

```bash
pnpm validate         # portable spec conformance
pnpm inspect          # deterministic component listing
pnpm payloads:build   # regenerate vendor payloads
pnpm payloads:verify  # fail if payloads drift from source
pnpm lint:plugin      # version lockstep, frontmatter, unshippable-content guard
pnpm test             # unit tests
```

See [docs/quality-gates.md](docs/quality-gates.md) for what each gate proves, and
[CONTRIBUTING.md](CONTRIBUTING.md) before making changes.

## License

MIT — see [LICENSE](LICENSE).
