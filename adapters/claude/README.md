# Claude review-orchestrator adapter

This companion adapter adds isolated Claude Code subagents around the portable
Monolithic Code Review Toolkit skills. Like the Codex adapter, it lives outside
`plugins/monolithic-code-review-toolkit/`: the portable payload contract ships
only `SKILL.md` files and cannot carry custom agents, hooks, or deterministic
helpers. It requires Python 3.12+ for its installer, guard, and hook.

## What differs from the Codex adapter

**The orchestrator is a skill in the main session, not an agent.**

On Codex the orchestrator is `mcrt_review_orchestrator`, an agent. It cannot
talk to the user, so a run that needs a human decision has to persist a
checkpoint and stop.

Claude Code subagents have no user channel either, but a skill running in the
main session does. So the orchestrator is `mcrt-review`, a skill, and the
worker-to-user round trip closes inside a single run:

1. A worker returns `status: "needs_input"` with a `questions` array.
2. `request-input` records the questions and moves the run to `pending_input`.
3. The skill asks the user with `AskUserQuestion`, in the session where the
   human actually is.
4. `resolve-input` records the answers and returns the run to `running`.
5. The skill sends the answers back with `SendMessage`, addressed to the worker
   **by agent name** — which resumes it from its transcript with full context.
   A fresh `Agent` call would start it cold and discard its work.

The checkpoint still exists and still survives a crash, but it is no longer the
only way to cross a decision point.

**The approval gate is enforced, not requested.** See *The poster guard* below.

**No `max_depth` configuration.** Claude Code caps subagent nesting at five
levels and the limit is not configurable, so the adapter needs no equivalent of
the Codex `agents.max_depth` edit.

**The Codex seven-day quota gate is omitted.** Claude Code exposes no
authoritative equivalent signal, and a guard that cannot read its input is worse
than no guard. `evaluate_quota` and its pause states are absent by design.

## Install

Install the plugin using the normal marketplace or release-payload method first.
Then install this adapter into the Claude scope you want:

```bash
python3.12 adapters/claude/install_claude_adapter.py --scope project --project /path/to/repository
python3.12 adapters/claude/install_claude_adapter.py --scope user
```

Use `--dry-run` to inspect the exact target. The installer refuses to overwrite
unmanaged agents or skills, records hashes for its own files, registers a
`PreToolUse` hook with a surgical `settings.json` edit that preserves unrelated
keys and other hooks, and restores only its own change during uninstall:

```bash
python3.12 adapters/claude/install_claude_adapter.py --scope project --project /path/to/repository --uninstall
```

Restart Claude Code, or run `/reload-skills`, after installing.

### Provider tools for the poster

The poster needs whatever tool actually writes a pull-request comment for your
provider. For CLI-based providers (GitHub through `gh`) that is `Bash`, which it
already has, and no flag is needed. For MCP-based providers, name the tools:

```bash
python3.12 adapters/claude/install_claude_adapter.py --scope project \
  --project /path/to/repository \
  --scm-tool mcp__azure-devops__repo_pull_request_thread_write \
  --scm-tool mcp__azure-devops__repo_pull_request_thread
```

`--scm-tool` is repeatable and appends to the poster's `tools:` line. Without
it the poster ships with no MCP tools at all, which is the correct default: a
worker that cannot reach a provider fails visibly instead of silently reaching
the wrong one.

`--scm-read-tool` does the same for the **read-only** workers, `discovery` and
`validator`, and is kept separate on purpose — a write tool must never reach a
worker whose job is to look. Without it those two can verify only capabilities
reachable through the shell, and will report MCP-based ones as unverified:

```bash
  --scm-read-tool mcp__azure-devops__repo_pull_request \
  --scm-read-tool mcp__azure-devops__wit_work_item
```

This matters more than it looks. `discovery` is asked which SCM capabilities
resolve; given no provider tools it cannot exercise an MCP mapping at all, and
the honest answer is "unverified", not a guess based on something adjacent that
happened to work.

## Review input

The main session builds a JSON-equivalent input and validates it through the
guard:

```json
{
  "workspace": "/absolute/path/to/repository",
  "review_type": "story-postflight",
  "pull_request_id": "123",
  "lenses": ["all"],
  "decision": "hold"
}
```

`review_type` is one of `task`, `story-preflight`, `story-postflight`,
`feature`, `pr-preparation`, or `pr-comment-triage`. `decision: "post"` requires
explicit `approved_finding_ids`; `hold` never invokes the posting agent. Code
fixes remain outside this adapter and require a separate explicit workflow.

## Agents and routing

| Agent | Model | Runs when |
| --- | --- | --- |
| `mcrt-review-discovery` | haiku | Only when setup, an SCM capability, or the diff boundary is unresolved |
| `mcrt-review-validator` | sonnet | Executes the selected lifecycle skill; returns only `VERIFIED` candidates |
| `mcrt-review-adversarial` | opus | Once, over the frozen candidate packet |
| `mcrt-review-poster` | sonnet | Only after the user approves, and only for approved ids |

Model tiers mirror the Codex routing: Luna→haiku for bounded mechanical
discovery, Terra→sonnet for review and posting, Sol→opus for the single
independent challenge.

Every worker runs sequentially. `Agent` and `Edit` are in each worker's
`disallowedTools`, so no worker can spawn another or edit source; the poster
additionally denies `Write`.

Note that Claude Code has no per-agent sandbox equivalent to Codex
`sandbox_mode = "read-only"`. Three workers hold `Bash`, so read-only is partly
a prompt-level constraint here. The one boundary that carries real consequences
— posting — is enforced by the hook instead.

## The poster guard

`hooks/mcrt_poster_guard_hook.py` is a `PreToolUse` hook that converts the
poster's approval rule from an instruction into an enforced boundary. The Codex
adapter can only ask a worker not to post an unapproved finding.

The poster marks every comment `[mcrt:<finding-id>]`. The hook then:

- refuses any marked write whose ids are not all in a completed checkpoint's
  `approved_finding_ids`;
- refuses any unmarked write while a checkpoint is `running`, `pending_input`
  or `pending_approval`;
- stays inert when there is no checkpoint directory or no run in flight, so
  ordinary manual pull-request comments are unaffected.

It covers both posting routes — MCP tools whose name looks like a pull-request
comment write, and shell commands that post through a provider CLI. A guard
that only knew MCP tool names would be blind on every `gh`-based provider.

The default matcher is `Bash|.*pull_request.*|.*pr_comment.*|.*issue_comment.*`
and can be overridden with `--matcher`. The hook self-filters, so a broader
matcher is safe but costs a process spawn per matched call.

## Deterministic utilities

`mcrt_review_guards.py` validates input and worker results, resolves the
lifecycle skill, tracks a single active checkpoint, manages the user-input round
trip, and reconciles approved finding IDs. It never performs semantic code
review or contacts a provider. Every command exits `2` with
`{"status": "blocked", "reason": "..."}` on stderr when a contract is violated.

```bash
python3.12 -m unittest discover -s adapters/claude/tests -t .
```

Azure DevOps, GitHub, and other providers work only when `review-setup` has
recorded their real SCM and requirement capabilities in
`.monolithic-code-review/sources.json`.
