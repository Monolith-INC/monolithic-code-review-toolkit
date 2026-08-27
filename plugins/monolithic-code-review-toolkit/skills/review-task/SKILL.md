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

### 4. Build an attention-ordered change map when it earns its place

Before detailed findings, add a change map only when the diff has multiple responsibilities or
significant review noise: for example, it crosses core behavior and wiring, spans several layers
whose relationship affects correctness, or generated/mechanical churn could hide a material change.
Do not produce one for a single-responsibility, easy-to-follow diff merely because it touches
multiple files.

Order the map by reviewer attention, not diff order:

1. **Core behavior** — algorithms, state transitions, domain rules, public contracts, and the
   tests that establish them. Name the reviewer entry point and the cross-file relationship it
   relies on.
2. **Wiring and integration** — routes, dependency wiring, configuration, adapters, and their
   relationship to the core behavior they invoke.
3. **Mechanical or generated** — formatting, renames, imports, generated files, and re-exports.
   List paths and statistics unless a concrete risk needs more context. Never call this group safe;
   it still needs proportionate review.

Use only the aid that removes a real comprehension barrier: pseudocode when syntax or nesting hides
the essential algorithm; a concrete before/after trace when the observable outcome is hard to
predict; and a labeled **Risk callout** only for a subtle, breaking, concurrent, security, or
performance-sensitive point. The map is an orientation aid, not a second diff or a finding list.

### 5. Record evidence before reporting

Treat every material discrepancy and criterion verdict as an evidence record: `id`, falsifiable
`claim`, `expected` requirement or invariant, decisive `evidence`, and (when applicable)
`baseline`, `treatment`, and `confounds`. Give it one verdict and disposition:

| Verdict | Meaning | Disposition |
| --- | --- | --- |
| `VERIFIED` | Evidence supports the claim and meets its stated threshold. | `report` |
| `NOT VERIFIED` | Evidence contradicts the claim or misses its stated threshold. | `drop` |
| `INCONCLUSIVE` | Missing or invalid access, baseline, measurement, or environment prevents a decision. | `local-uncertainty` |

Category and severity are independent of this verdict. Only `VERIFIED` discrepancies become
findings. Keep `INCONCLUSIVE` records in the local uncertainty section; do not present them as
findings or soften them into warnings.

### 6. Report

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

### Change map
- **Core behavior** — `<entry path:line>` — reviewer entry point: <where to start>.
  Relationship: `<caller>` → `<domain rule>` → `<observable result>`.
- **Wiring and integration** — `<path>` — connects <dependency or route> to <core entry point>.
- **Mechanical or generated** — `<paths and statistics>` — <why it is present and any review risk>.

Include this section only when the trigger above is met. Omit empty groups and any unneeded
pseudocode, trace, or risk callout.

### [high] error — src/auth/token.ts:42
**Found** — Refresh path returns the expired token when `renew()` throws.
**Consequence** — Callers treat the failure as success; sessions silently outlive revocation.
**Suggested** — Propagate the error; let the caller decide to re-authenticate.
```

Close with the criteria that are **not verifiable from the diff**, so the user knows what the review
did not cover, and list local uncertainty records separately.

## Manual evaluation cases

- Supported claim: a changed line returns an expired token on a documented `renew()` failure path;
  record the caller trace and requirement as evidence, mark `VERIFIED`, and report the existing
  `Found → Consequence → Suggested` finding.
- Disproved claim: a suspected missing validation is already enforced by the changed parser and its
  focused test; mark `NOT VERIFIED` and omit it from findings.
- Inaccessible evidence: a DoD requires deployment configuration that is unavailable in the diff or
  repository; mark `INCONCLUSIVE` with the missing access as a confound and list it only under local
  uncertainty.
- Multi-responsibility diff: a task touches core behavior, wiring, and generated output; produce the
  three-group change map with reviewer entry points before findings.
- Trivial diff: a single-responsibility change in one module; omit the change map entirely.

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
