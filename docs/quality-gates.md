# Quality gates

## Required before every commit

Run on a clean checkout. The first toolkit-backed command clones and builds the pinned toolkit into
`.toolkit/` and takes about a minute; later runs reuse it.

```bash
pnpm validate         # portable spec conformance
pnpm inspect          # deterministic component listing
pnpm payloads:verify  # vendor payloads match their source
pnpm lint:plugin      # repository invariants
pnpm test             # unit tests
```

Requires git, Node.js ≥ 22, and Python 3.10+. `pnpm` itself need not be on `PATH` — the pinned
version is resolved through `npx` when it is absent.

## What each gate proves

| Gate                   | Proves                                                                                                                        |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `pnpm validate`        | The plugin root is a conformant Agent Plugins v1.0.0 root. Expect `{"ok":true}`.                                                |
| `pnpm inspect`         | Every skill is discoverable and the manifest parses as intended. Expect `diagnostics: []` and one entry per skill.               |
| `pnpm payloads:verify` | Committed payloads are exactly what the current source compiles to, for all three vendors. Catches a hand-edited payload.        |
| `pnpm lint:plugin`     | Version lockstep, the portable frontmatter contract, and the guard against content adapters would silently drop.                 |
| `pnpm test`            | The validator itself behaves — every failure mode covered, plus an assertion that this repository validates.                     |

## Guardrails

- **Never hand-edit `payloads/`.** It is build output. Change the portable source and run
  `pnpm payloads:build`. `payloads:verify` exists to catch exactly this mistake.
- **Never add files to a skill directory besides `SKILL.md`.** Adapters ship nothing else, so the
  content would be invisible at runtime while looking present in the repository. `lint:plugin` fails
  on it.
- **Never add `commands/`, `agents/`, or `hooks/` to the plugin root.** No adapter emits them.
- **Keep `VERSION`, `package.json`, and `plugin.json` in step**, and rebuild payloads after a version
  bump — the payload records the version it was built from.
- **Bump the toolkit pin deliberately.** `TOOLKIT_REF` in `scripts/with_toolkit.sh` is what makes
  validation reproducible. Changing it can change what conformance means, so treat it as a reviewed
  change and re-run every gate afterwards.

## CI

Two jobs, split by cost.

**`checks`** — ubuntu, macOS, and Windows × Python 3.10 and 3.12. Runs `validate_plugin.py` and the
unit tests. No toolkit checkout, so it is fast and covers every platform a contributor might author
on.

**`conformance`** — ubuntu only. Builds the pinned toolkit (cached on the hash of
`with_toolkit.sh`) and runs `validate`, `inspect`, and `payloads:verify`. This is the job that proves
the template has not been deviated from.

The release workflow runs both gate sets again before publishing, so no release can be cut from a
repository that does not validate.

## Beyond the gates

The gates prove conformance and structure. They cannot prove the skills work — that needs a real
pull request:

- `review-setup` in a repository **with** a tracker MCP present, and in one with **none** (must fall
  back to a vault or `gh issue` without erroring).
- `review-task` against a deliberately scope-violating diff — the off-scope work must be named.
- `review-story-postflight` against a real pull request — comments must land on correct `file:line`
  anchors. This is the highest-risk behaviour in the toolkit; see ADR-0001.
- `triage-pr-comments` on a pull request carrying human comments — the canvas must show all four
  attributes per comment.
- `respond-pr-comments` with no user instruction — it must do nothing. This is the guard test.

## Optional extra check

If the Claude Code CLI is available, its own manifest validator can be run against the compiled
payload as an independent second opinion:

```bash
claude plugin validate payloads/claude/payload --strict
```

Not part of CI, since it depends on a host CLI rather than on the template.
