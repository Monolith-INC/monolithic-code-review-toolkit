---
type: orientation
tags:
  - agent
  - orientation
  - index
created: 2026-08-12
---

# Agent Orientation

> Read this file first. Replaces workspace exploration.

## Workspace

| Root | Role |
| --- | --- |
| `monolithic-code-review/` | Plugin / toolkit source |
| `AI_Codex/` | This vault — permanent memory + ledgers |

Project brief: see repo-root `instructions.md`.

## Slash commands

| Command | Purpose |
| --- | --- |
| `/agent-continuity:init-workspace` | Scaffold the CLAUDE.md tree. |
| `/agent-continuity:init-vault` | Scaffold this vault skeleton. |
| `/agent-continuity:init-rules` | Drop starter `.agent/rules/*.md` templates. |
| `/agent-continuity:mine-bases` | Backfill frontmatter + Base dashboards (software-project). |
| `/agent-continuity:query-vault` | Read-only live query of the vault via the Obsidian CLI. |
| `/agent-continuity:canvas-map` | Generate an Architecture Canvas relationship map. |
| `/agent-continuity:research-ingest` | Ingest a URL into a source-stamped reference note. |
| `/agent-continuity:vault-lint` | Audit the vault against its archetype spec. |

## Knowledge index

| Note | Role |
| --- | --- |
| [[Agent_Orientation]] | This file — entry point |
| [[../README\|Vault README]] | Taxonomy map |

## Conventions

- **Status is the folder** (`Tickets/Active/`, etc.) — never duplicate `status` in frontmatter.
- Naming and required frontmatter keys live in the archetype spec (`software-project.json`).
- Enforcement: `PreToolUse(Write)` hook + `/agent-continuity:vault-lint`.
