---
name: review-task
description: Use when a small unit of work is complete, before committing or handing off, to check the changes actually introduced against that task's requirements and goals and report any discrepancies.
---

# Review Task

A task is the smallest unit of work. This skill compares **what the diff actually does** against
**what the task asked for**, and reports discrepancies. It changes no code and posts nothing —
the output is a report for the user.

Requires `.monolithic-code-review/sources.json`. If it is missing, run `review-setup` first.

## Procedure

### 1. Establish what was asked

Read `.monolithic-code-review/sources.json`. Resolve the task through the recorded
`fetch_work_item` capability. Infer the id from the branch name or recent commit subjects using
`conventions.work_item_pattern` when the user did not name one; confirm the inferred id before
proceeding.

Extract, and keep them separate — they are checked differently:

- **Goal** — the outcome the task exists to produce.
- **Requirements** — specific things that must be true.
- **Definition of done / acceptance criteria** — the completion test.
- **Out of scope** — anything the task explicitly excludes.

If the tracker lists `fetch_work_item` under `unsupported`, say so and ask the user to paste the
requirements. **Never invent requirements to review against** — a review against imagined criteria is
worse than no review.

### 2. Establish what changed

```bash
git status --short
git diff --stat
git diff
```

For work already committed on a branch, diff against the base instead:

```bash
git diff $(git merge-base HEAD <base-branch>)...HEAD
```

Read the changed files in full, not just the hunks. A diff hides whether a function's other callers
still hold. Also read the files that import or are imported by the changed ones — most requirement
violations surface at the boundary, not inside the hunk.

### 3. Check the diff against each criterion

Walk the requirements one at a time. For each, decide: **satisfied**, **partially satisfied**,
**not satisfied**, or **not verifiable from the diff**. The last is a real answer — say it rather
than guessing.

Then look for what the requirements did not ask for:

| Category        | What it means                                                                          |
| --------------- | -------------------------------------------------------------------------------------- |
| **error**       | The change is wrong: a bug, a broken contract, a regression                              |
| **gap**         | A requirement or DoD item is unmet or only partly met                                    |
| **improvement** | A pertinent improvement — one tied to this task's goal, not a general code-quality wish   |
| **off-scope**   | Work present in the diff that no requirement asked for, including anything marked out of scope |

Hold `improvement` to a high bar. If it would apply equally to code this task never touched, it does
not belong in this report.

### 4. Report

Report only what you found. **If there are no discrepancies, say so in one line and stop** — do not
manufacture findings to justify the review.

Every finding follows the same three-part contract:

> **Found** — what is there, with `file:line`
> **Consequence** — what it costs or breaks, concretely
> **Suggested** — the specific action to take

Order findings by severity: **critical**, **high**, **medium**, **low**.

| Severity     | Applies to                                                                              |
| ------------ | ---------------------------------------------------------------------------------------- |
| **critical** | Security holes, data loss, complete failure of the task's goal                            |
| **high**     | Functional bugs contrary to intent, unmet DoD items, resource leaks, N+1 queries          |
| **medium**   | Partially met requirements, missing input validation, logic that is correct but fragile   |
| **low**      | Off-scope additions that are harmless, minor clarity issues in the changed lines          |

Format:

```text
## Task review — <task id>: <title>

<n> finding(s). Requirements: <x> satisfied, <y> partial, <z> unmet.

### [high] error — src/auth/token.ts:42
**Found** — Refresh path returns the expired token when `renew()` throws.
**Consequence** — Callers treat the failure as success; sessions silently outlive revocation.
**Suggested** — Propagate the error; let the caller decide to re-authenticate.
```

Close with the criteria that are **not verifiable from the diff**, so the user knows what the review
did not cover.

## Constraints

- Comment only on lines the diff actually changes. Surrounding code is context for judgement, not a
  target for findings.
- Do not tell the user to "check", "verify", "confirm", or "ensure" something — determine it
  yourself, or state plainly that it is not verifiable from the diff.
- Do not explain the change back to its author.
- No stylistic nits: formatting, trailing newlines, or naming preferences that do not affect
  behaviour or comprehension.
- Test files get a lighter pass — wrong assertions and missing coverage of a stated requirement
  count; test style does not.

## Success criteria

- Every requirement and DoD item has an explicit verdict.
- Every finding carries all three parts and a `file:line`.
- Off-scope work is named, not silently accepted.
- A clean diff produces a one-line clean report.
