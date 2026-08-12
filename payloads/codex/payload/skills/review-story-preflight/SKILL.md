---
name: review-story-preflight
description: Use when a user story is finished but before pushing the last commits or opening a pull request, to check the whole story branch against the story description, requirements and definition of done.
---

# Review Story — Pre-flight

The gate between "the work is done" and "the work becomes a pull request". This reviews the
**entire story branch**, not a single task, against the story's own description, requirements, and
definition of done. Nothing is pushed and nothing is posted — findings go to the user, who decides
what to fix before the PR exists.

Requires `.monolithic-code-review/sources.json`. If it is missing, run `review-setup` first.

## Why this is not `review-task` on a bigger diff

A story is complete in a way individual tasks are not. Three checks only make sense at this level:

1. **Coherence across tasks.** Task 3 may have quietly undone what task 1 established. Only the
   whole-branch diff shows it.
2. **The definition of done as a whole.** Individual tasks can each pass while the story's DoD
   still fails — most often documentation, migrations, or observability nobody's task owned.
3. **Readiness to be reviewed by a human.** Debug statements, commented-out code, `TODO`s added
   during the work, and commits that will confuse a reviewer.

## Procedure

### 1. Establish what the story asked for

Resolve the story through `fetch_work_item`. Also call `fetch_parent` to get the feature it belongs
to — a story can satisfy its own text while contradicting its parent's intent, and that is worth
knowing before a human reviewer finds it.

Extract goal, requirements, DoD, and out-of-scope statements. If `fetch_work_item` is unsupported,
ask the user for the story text rather than inferring it.

### 2. Establish the whole-branch diff

```bash
git branch --show-current
git fetch origin
BASE=$(git merge-base HEAD origin/<base-branch>)
git diff --stat $BASE...HEAD
git diff $BASE...HEAD
git log --oneline $BASE..HEAD
```

Determine the base branch from the story's parent feature branch when the workflow stacks branches,
otherwise from the repository default. Confirm the base with the user if it is ambiguous — diffing
against the wrong base produces a review of unrelated work.

Read changed files in full, plus their immediate callers and callees.

### 3. Review

Apply the same categories and severities as `review-task`:

| Category        | What it means                                                                          |
| --------------- | -------------------------------------------------------------------------------------- |
| **error**       | The change is wrong: a bug, a broken contract, a regression                              |
| **gap**         | A requirement or DoD item is unmet or only partly met                                   |
| **improvement** | A pertinent improvement, tied to this story's goal                                       |
| **off-scope**   | Work no requirement asked for, including anything the story excluded                     |

Severities are **critical**, **high**, **medium**, **low**, as in `review-task`.

Then run the pre-flight checks that are specific to this gate:

- **Cross-task contradictions** — a later commit reverting or bypassing an earlier one.
- **Parent-feature agreement** — does this story move its feature toward its stated goal?
- **Leftovers** — debug logging, commented-out blocks, `TODO`/`FIXME` added by this branch,
  temporary fixtures, credentials or endpoints pointing at development environments.
- **Commit legibility** — commits a reviewer can follow. Say so if the history would be materially
  clearer squashed or reordered; do not rewrite it yourself.
- **Verification evidence** — do tests, migrations, or docs the DoD requires actually exist in the
  diff? Run the project's test command if one is discoverable, and report the real result.

### 4. Report

Same three-part contract:

> **Found** — what is there, with `file:line`
> **Consequence** — what it costs or breaks, concretely
> **Suggested** — the specific action to take

```text
## Story pre-flight — <story id>: <title>

Branch <head> vs <base>, <n> commits, <m> files.
Requirements: <x> satisfied, <y> partial, <z> unmet. DoD: <a>/<b> met.

VERDICT: ready for pull request | blocked by <n> finding(s)

### [high] gap — no migration for the new column
**Found** — `orders.status` is read in src/orders/repo.ts:88 but no migration adds it.
**Consequence** — Deploy fails on any environment whose schema predates this branch.
**Suggested** — Add the migration to db/migrations/ and note it in the story's DoD checklist.
```

End with an explicit verdict line. "Ready for pull request" means every DoD item is met and no
critical or high finding is open. Anything less is blocked, and the report says by what.

Close with criteria **not verifiable from the diff**.

## Constraints

- Read-only. Do not push, do not open a pull request, do not amend commits.
- Comment only on changed lines.
- Do not tell the user to "check" or "verify" — determine it, or state it is not verifiable.
- No stylistic nits.
- If the branch is already pushed and a PR exists, this is the wrong skill — use
  `review-story-postflight`.

## Success criteria

- Every requirement and DoD item has an explicit verdict.
- The whole-branch diff was reviewed against the correct base.
- Pre-flight leftovers were checked for explicitly.
- The report ends with a ready/blocked verdict.
