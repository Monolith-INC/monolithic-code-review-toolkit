---
name: review-feature
description: Use when a whole feature is complete, to run a rigorous adversarial review of the full feature diff against the feature's documented goal, definition of done and out-of-scope instructions.
---

# Review Feature

The strictest gate in this toolkit. A feature is the unit the business actually asked for, so the
first question is not "is this code good" but **"is this diff in agreement with what the feature said
it would do"**.

Requires `.monolithic-code-review/sources.json`. If it is missing, run `review-setup` first.

## Order of priority

Work in this order and do not reorder it. A feature that is well-built and wrong is still wrong.

1. **Agreement with the definition of done.** Every DoD item, explicitly, one at a time.
2. **Agreement with the goal.** Does the delivered behaviour produce the outcome the feature exists
   for? A feature can satisfy every listed requirement and still miss its point.
3. **Agreement with the out-of-scope instructions.** Anything the feature explicitly excluded that
   appears in the diff is a finding, regardless of merit.
4. **Only then**: correctness, security, performance, maintainability.

## Procedure

### 1. Ingest the feature's own documentation

Resolve the feature through `fetch_work_item`, and every child story through the tracker. Pull specs
and design documents through `list_linked_artifacts`. Read them all before reading any code — the
point of this skill is to review against intent, and intent has to be in hand first.

Build an explicit checklist of DoD items and out-of-scope statements. If the feature's documentation
does not state a DoD, say so and ask the user for it. **A feature review without a definition of done
is not a feature review** — do not substitute your own judgement of what "done" should mean.

### 2. Establish the full feature diff

```bash
git fetch origin
BASE=$(git merge-base HEAD origin/<trunk>)
git diff --stat $BASE...HEAD
git diff $BASE...HEAD
git log --oneline --no-merges $BASE..HEAD
```

For a feature under review as a pull request, use the remote diff instead:

```bash
gh pr view <PR> -R <owner>/<repo> --json title,body,baseRefName,headRefOid,files
gh pr diff <PR> -R <owner>/<repo>
```

Confirm the base is the trunk the feature merges into, not an intermediate story branch.

### 3. Review, harder than at story level

Apply the four categories — **error**, **gap**, **improvement**, **off-scope** — and the four
severities — **critical**, **high**, **medium**, **low**.

What is raised here that would not be raised at story level:

- **Seams between stories.** Each story may be internally consistent while the interfaces between
  them disagree. Read across the boundaries.
- **Architectural drift.** Does the feature as built match the design it was approved against? Name
  the divergence and whether it is justified.
- **Whole-feature behaviour under failure.** Partial failure, retry, and rollback across the feature,
  not within one story.
- **Migration and rollout.** Schema changes, feature flags, backward compatibility for callers that
  predate the feature, and whether the feature can be turned off.
- **Observability.** Can an operator tell whether this feature is working in production?
- **What was silently dropped.** Compare the delivered diff against the full set of child stories.
  Anything scoped but not delivered is a `gap`, whether or not its story was closed.

Fact-check as in `review-story-postflight`: verify library and API behaviour against current official
documentation via Context7 or web search, cite the specific DoD line behind every `gap`, and drop
findings that do not survive.

### 4. Report

```text
## Feature review — <feature id>: <title>

<n> commits across <m> stories, <k> files, base <trunk>.

### Agreement
- Definition of done: <a>/<b> met
- Goal: met | partially met | not met — <one line>
- Out of scope: <n> violation(s)

VERDICT: in agreement | not in agreement — <reason>

### Findings
### [critical] gap — DoD item 4 "rollback path" is not implemented
**Found** — Migration db/migrations/014 has no down path.
**Consequence** — A failed rollout cannot be reverted without manual surgery on production data.
**Suggested** — Add the down migration, or amend the DoD if irreversibility is deliberate.
```

Lead with the agreement section and the verdict. Findings follow. Every finding carries
**Found → Consequence → Suggested** and a `file:line`.

Close with criteria **not verifiable from the diff**.

### 5. Apply the outcome

The brief for this stage expects the review to end in action. After reporting, ask the user which
findings to act on. Then, and only on their instruction:

- Post findings to the feature's pull request — hand off to `review-story-postflight`, which owns the
  posting mechanics.
- Address reviewer comments already on the pull request — hand off to `triage-pr-comments`, then
  `respond-pr-comments`.

Do not post or edit code from this skill without being asked to.

## Constraints

- Agreement with the documented feature comes before code quality. Never lead with a style finding.
- Comment only on changed lines.
- Do not tell the user to "check" or "verify" — determine it, or state it is not verifiable.
- Do not invent a definition of done.

## Success criteria

- Every DoD item and out-of-scope statement has an explicit verdict.
- The report leads with agreement and a verdict, not with code findings.
- Scoped-but-undelivered work is named.
- Every finding was fact-checked and cites its evidence.
