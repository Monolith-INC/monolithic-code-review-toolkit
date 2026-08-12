---
title: Skill runtime under the adapter payload allowlist
type: adr
status: accepted
created: 2026-08-12
decision-date: 2026-08-12
revisit-after: v0.1.0
tags:
  - adr
  - agent-plugins-toolkit
  - packaging
  - skills
---

# ADR-0001 — Skill runtime under the adapter payload allowlist

## Status

**Accepted**, with an explicit commitment to revisit after the v0.1.0 release.

## Context

The project brief names [Monolith-INC/agent-plugins-toolkit][toolkit] as the architectural template
and forbids deviation from it. Planning assumed skills could bundle helper code and reference
documents, because both target hosts document exactly that: Claude Code shows `SKILL.md` alongside
`reference.md` and `scripts/`, and the Codex skill-creator sample documents bundled `scripts/`,
`references/`, and `assets/`.

**The toolkit is stricter than the hosts it targets.** Verified in the adapter sources at pin
`b75aaa5c627599f1fdb25caff154e9a22d2e2640`, every vendor adapter enforces a payload path allowlist:

| Vendor | Allowed payload paths                                                                                    |
| ------ | -------------------------------------------------------------------------------------------------------- |
| claude | `.claude-plugin/plugin.json`, `skills/<name>/SKILL.md`, `hooks/hooks.json`, `.mcp.json`                  |
| codex  | `.codex-plugin/plugin.json`, `skills/<name>/SKILL.md`, `hooks/hooks.json`, `.mcp.json`                   |
| cursor | `.cursor-plugin/plugin.json`, `skills/<name>/SKILL.md`, `rules/<id>.mdc`, `hooks/hooks.json`, `mcp.json` |

`compileClaudePayload` and its siblings map skills with
`plugin.skills.map((skill) => createMarkdownPayloadFile({ path: skill.path, content: skill.content }))`
— the `SKILL.md` body and nothing else. Any additional file is rejected by `validate*Bundle` with a
`*.payload.path` diagnostic.

Three consequences follow:

1. Helper scripts cannot travel inside the payload.
2. Shared reference documents cannot travel inside the payload either, so the planned `shared/`
   directory with a `sync_shared.py` mirror step has no destination.
3. No adapter emits a `commands/` directory, so slash-command surfaces cannot ship even though
   Cursor and Codex both support them natively.

## Decision

**Skills are fully self-contained `SKILL.md` documents.** Each skill carries its complete procedure
inline and drives `gh`, `git`, and shell commands directly, relying on the agent's own reasoning
rather than on packaged helper code.

Repository tooling is unaffected — `scripts/validate_plugin.py` and `scripts/build_payloads.mjs`
are development tools that never enter a payload, and remain free to be whatever language suits.

## Options considered

| Option                              | Effect                                                                                                                                                                                                                                                               | Verdict                         |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| **Self-contained skills**           | All procedure inline in `SKILL.md`. Nothing to install. No unit-testable logic; longer skill documents.                                                                                                                                                              | **Chosen for v0.1.0**           |
| Separate PyPI runtime               | Payload stays pure; `review-setup` installs a `monolithic-code-review` package and skills shell out to its CLI. Keeps diff line-anchoring deterministic and unit-tested. Costs a second release channel and a `pip` dependency. This is the [fp-enforcer][fp] model. | Deferred — revisit after v0.1.0 |
| Helpers fetched into target project | `review-setup` clones or downloads helpers into the consuming repo's `.monolithic-code-review/`. Avoids PyPI but makes install messier and versioning manual.                                                                                                        | Rejected                        |

## Consequences

- Zero deviation from the template, which is the brief's highest-priority constraint.
- Nothing for a user to install beyond the plugin itself.
- Diff hunk parsing and pull-request comment line-anchoring are performed by the agent rather than by
  tested code. **This is the weak point of the decision** and the main reason to revisit: inline
  comment positions are easy to get wrong, and a helper would make them deterministic.
- No slash-command surface on Cursor or Codex. Skills are the invocation surface on all three hosts.
- Skill documents carry more procedural detail than they otherwise would, which raises the cost of
  keeping repeated guidance consistent across the seven skills.

## Revisit trigger

Reassess immediately after the v0.1.0 release, or sooner if post-flight review comments land on wrong
lines in practice. The PyPI-runtime option is the designated fallback and needs no rework of the
portable manifest to adopt — only new skill bodies and a `review-setup` install step.

Also worth re-checking upstream at that point: whether the toolkit has relaxed the payload allowlist
to carry bundled skill resources.

## Related

- Hooks and rules *are* portable and need no deviation: declare them in `plugin.json` under
  `extensions["org.agent-plugins.distribution"]` as `rules[]` and `hookIntents[]`.

[toolkit]: https://github.com/Monolith-INC/agent-plugins-toolkit
[fp]: https://github.com/theocarranza/fp-enforcer
