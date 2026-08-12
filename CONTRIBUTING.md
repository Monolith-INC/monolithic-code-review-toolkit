# Contributing

## The one rule

The plugin under `plugins/monolithic-code-review-toolkit/` is a **portable Agent
Plugins v1.0.0 root**. It conforms to
[Monolith-INC/agent-plugins-toolkit](https://github.com/Monolith-INC/agent-plugins-toolkit)
and does not deviate from it. Everything below follows from that.

## What a payload may contain

Every vendor adapter enforces a payload path allowlist. Nothing outside it can
be shipped:

| Vendor | Allowed payload paths                                                                                    |
| ------ | -------------------------------------------------------------------------------------------------------- |
| claude | `.claude-plugin/plugin.json`, `skills/<name>/SKILL.md`, `hooks/hooks.json`, `.mcp.json`                  |
| codex  | `.codex-plugin/plugin.json`, `skills/<name>/SKILL.md`, `hooks/hooks.json`, `.mcp.json`                   |
| cursor | `.cursor-plugin/plugin.json`, `skills/<name>/SKILL.md`, `rules/<id>.mdc`, `hooks/hooks.json`, `mcp.json` |

The compile step maps each skill to its `SKILL.md` body and nothing else, so:

1. **Skills are self-contained.** No bundled `references/`, `scripts/`, or
   `assets/` — they would not travel, and would be rejected as
   `*.payload.path`. Write the whole procedure into `SKILL.md`. See
   [ADR-0001](AI_Codex/Architecture/ADR/ADR-0001-skill-runtime-under-payload-allowlist.md).
2. **No commands.** No adapter emits a `commands/` directory. Skills are the
   invocation surface on all three hosts.
3. **`payloads/` is generated.** Rebuild with `pnpm payloads:build`; never edit
   a file in it. `pnpm payloads:verify` fails CI if it drifts from source.

Repository tooling under `scripts/` and `tests/` never enters a payload, so it
is free to be any language.

## Hooks and rules are portable

They need no vendor-specific file. Declare them in `plugin.json` under
`extensions["org.agent-plugins.distribution"]` as `rules[]` and `hookIntents[]`;
each adapter renders them into its own native shape.

## Skill frontmatter stays portable

`SKILL.md` frontmatter is `name` and `description` only, and `name` must equal
the directory name.

## Version lockstep

`VERSION`, `package.json`, and `plugins/<name>/plugin.json` carry the same
version. `pnpm lint:plugin` enforces it.

## Before opening a PR

```bash
pnpm validate        # toolkit conformance
pnpm inspect         # deterministic component listing
pnpm sync:verify     # shared-file mirrors are current
pnpm lint:plugin     # version lockstep, frontmatter, structure
pnpm payloads:verify # vendor payloads match their source
pnpm test            # python unit tests
```

The first invocation clones and builds the pinned toolkit into `.toolkit/` and
takes a minute; later runs reuse it.
