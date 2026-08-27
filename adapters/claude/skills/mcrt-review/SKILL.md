---
name: mcrt-review
description: Runs a Monolithic Code Review Toolkit lifecycle review through isolated subagent workers — discovery, validation, an independent adversarial pass, and gated pull-request posting. Use when asked to review a task, story, feature or pull request against its requirements, or to post approved review findings. Keeps every user decision in the main session.
---

<!-- Managed by the Monolithic Code Review Toolkit Claude adapter. -->

# MCRT Review Orchestrator

This skill is the orchestrator of the Claude review adapter. It runs the same four-worker pipeline
as the Codex adapter, with one deliberate difference: **the orchestrator is this skill, running in
the main session, not a subagent.**

That matters because the orchestrator is the only participant that can talk to the user. Workers
are isolated subagents with no user channel. When a worker needs a decision, the question is
routed up to this session, asked, and the answer is sent back down to the same worker with its
context intact. On Codex the orchestrator is itself an agent, so the run has to checkpoint and
stop; here it can simply ask.

Semantic judgement lives in the workers. Mechanical state lives in `mcrt_review_guards.py`. This
skill sequences them and owns every user interaction.

## Before anything

`.monolithic-code-review/sources.json` must exist. If it does not, stop and run
`monolithic-code-review-toolkit:review-setup` first — every worker depends on the capability
mappings it records.

Run one worker at a time. Never run two in parallel: the adversarial pass must see the
validator's frozen output, and the poster must see the completed approval.

## Phase 0 — open the run

Build the review input and hand it to the guard. `review_type` is one of `task`,
`story-preflight`, `story-postflight`, `feature`, `pr-preparation`, `pr-comment-triage`.

```bash
python3.12 __MCRT_ADAPTER_ROOT__/mcrt_review_guards.py create-checkpoint <input.json>
```

The guard validates the input, resolves the namespaced lifecycle skill, and refuses a second
concurrent run. It prints the checkpoint path — every later command needs it. Create a run
directory beside it for worker output.

If the guard reports an existing active checkpoint, resolve that run before starting another.
`active <workspace>` reports which one.

## Phase 1 — discovery (conditional)

Dispatch `mcrt-review-discovery` **only** when setup, an SCM capability, or the diff boundary is
unresolved. A clean run with a known pull request skips this phase entirely; it costs a model
call and buys nothing when the facts are already in hand.

## Phase 2 — validation

Dispatch `mcrt-review-validator` with the workspace, the qualified lifecycle skill, the frozen
identifiers, the requested lenses, and the run directory. It executes the toolkit skill and
returns only `VERIFIED` candidates.

```bash
python3.12 __MCRT_ADAPTER_ROOT__/mcrt_review_guards.py append-result <checkpoint> <result.json>
```

The guard refuses a result whose findings are not all `VERIFIED`, whose ids collide, or whose
`selected_skill` does not match what was requested.

## Phase 3 — the adversarial pass

Dispatch `mcrt-review-adversarial` **once**, with the verified candidates and the frozen evidence
packet. Do not substitute it, repeat it, or loop it — a second challenge pass on the same packet
is how a review talks itself into findings.

```bash
python3.12 __MCRT_ADAPTER_ROOT__/mcrt_review_guards.py append-adversarial <checkpoint> <result.json>
```

A complete result must decide every candidate exactly once, and moves the checkpoint to
`pending_approval`.

## Phase 4 — approval, in this session

Present the accepted findings to the user and ask which to post. Use `AskUserQuestion`. Rejected
and inconclusive items are shown for context but cannot be approved — the guard refuses an
approval naming anything the adversarial pass did not accept.

```bash
python3.12 __MCRT_ADAPTER_ROOT__/mcrt_review_guards.py complete <checkpoint> <approved.json>
```

Approving nothing is a legitimate outcome. Say so plainly and stop.

## Phase 5 — posting

Only with an explicit user instruction to post, and only after the checkpoint reads `completed`.

Dispatch `mcrt-review-poster` with the checkpoint path and the approved ids. It marks every
comment `[mcrt:<finding-id>]`, and the `PreToolUse` hook refuses any pull-request write whose ids
are not approved. The hook is the enforcement; the agent instructions are not.

Code fixes are outside this skill. Applying a finding is a separate, explicitly requested action.

## The ask round-trip

This is the part that differs from the Codex adapter, and it is the reason the orchestrator lives
here rather than in a subagent.

A worker that cannot proceed without a human decision returns:

```json
{"status": "needs_input", "questions": [{"id": "q1", "question": "...", "options": ["A", "B"]}]}
```

Handle it in this order:

1. **Record it.** `request-input <checkpoint> <result.json>` moves the run to `pending_input` and
   stores the questions. The guard rejects a `needs_input` result with no questions, and refuses
   to accept one through `append-result`.
2. **Ask the user** with `AskUserQuestion`, in this session, using the worker's own wording.
3. **Record the answers.** `resolve-input <checkpoint> <answers.json>`, shaped
   `{"answers": {"q1": "..."}}`. The guard requires every question answered and rejects answers
   naming a question that was not asked. The run returns to `running` and the exchange is logged
   in `input_exchanges`.
4. **Send the answers back down.** Use `SendMessage` addressed to the worker **by its agent name**
   — `mcrt-review-validator`, not a fresh `Agent` call. A send resumes that worker from its
   transcript with full context; a new `Agent` call starts it cold and loses the work it already
   did.

Never answer a worker's question yourself, and never guess to keep the run moving. The whole
point of routing the question here is that this is where the human is.

## What this skill never does

- Review source or judge a finding itself. That is the workers' job.
- Post, reply, resolve, approve, or vote on a pull request outside `mcrt-review-poster`.
- Edit source or commit.
- Approve findings on the user's behalf.

## Reference

- Checkpoints: `.monolithic-code-review/orchestrator/checkpoint-<run-id>.json`
- Guard commands: `validate-input`, `create-checkpoint`, `active`, `append-result`,
  `request-input`, `resolve-input`, `append-adversarial`, `complete`
- Every guard command exits `2` with `{"status": "blocked", "reason": "..."}` on stderr when a
  contract is violated. A blocked guard is a stop, not a prompt to retry with different arguments.
