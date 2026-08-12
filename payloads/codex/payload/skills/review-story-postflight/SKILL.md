---
name: review-story-postflight
description: Use after a pull request has been opened for a user story, to run an adversarial review of the remote diff against the story specs and post categorized review comments to the pull request.
---

# Review Story — Post-flight

An adversarial review of the **remote pull request diff**, fact-checked against the story's own
artifacts and against current official documentation, then posted to the pull request as review
comments.

This skill **writes to the pull request**. Confirm with the user before posting.

Requires `.monolithic-code-review/sources.json` and authenticated `gh`.

## Stance

Adversarial means assuming the change is wrong until the diff shows otherwise. Trace the logic
rather than reading it. Prefer the failing case over the happy path. A review that finds nothing is
a legitimate outcome, but it must be the result of having genuinely looked for failure.

It does **not** mean hostile, exhaustive, or nitpicking. Every posted comment costs the author
attention; spend it only where something is actually at stake.

## Procedure

### 1. Ingest

Read `.monolithic-code-review/sources.json` for `scm.owner`, `scm.repo`, and
`conventions.tag_pr_author`. Always pass `-R <owner>/<repo>` so a fork or multi-remote checkout
cannot mix repositories.

```bash
gh auth status
gh pr view <PR> -R <owner>/<repo> --json title,body,baseRefName,headRefName,author,files
gh pr diff <PR> -R <owner>/<repo>
```

Resolve the story through `fetch_work_item`, its feature through `fetch_parent`, and any specs or
design documents through `list_linked_artifacts`. The pull request body is a claim about the work;
the story is the requirement. When they disagree, that disagreement is itself a finding.

If the diff is large, work file by file rather than trying to hold it all at once. Read the full
current content of each changed file — the diff alone hides whether other call sites still hold.

### 2. Scan for four things

| Category        | What to look for                                                                        |
| --------------- | ---------------------------------------------------------------------------------------- |
| **error**       | Bugs, broken contracts, regressions, race conditions, unhandled failures, security holes   |
| **gap**         | Requirements or DoD items the diff does not meet                                          |
| **improvement** | Improvements pertinent to *this* story's goal — not general code-quality wishes            |
| **off-scope**   | Changes no requirement asked for, including anything the story or feature excluded         |

Trace deliberately for: off-by-one errors, null and error paths, resource cleanup, concurrent
access, input that crosses a trust boundary, and any contract this diff changes for existing
callers.

### 3. Fact-check before posting

This is what separates this skill from a first-pass review. **Every finding must survive
verification, and unverified findings are dropped rather than hedged.**

- **Against official documentation.** When a finding depends on how a library, framework, or API
  behaves, verify it against current official docs — use Context7 for library documentation, and web
  search for anything else. Training recall is not evidence; APIs change.
- **Against the story artifacts.** A `gap` finding must cite the specific requirement or DoD line it
  fails. If you cannot cite one, it is not a gap — it is at best an improvement.
- **Against the codebase.** A claimed regression must be checked against the code that exists, not
  the code you expect. Read the callers.
- **Against the diff boundary.** Confirm the line you are commenting on is actually added or
  modified by this pull request.

Drop anything that does not survive. State how many findings you dropped and why — that number tells
the user how much the fact-checking is doing.

### 4. Confirm with the user

Show the surviving findings as a table — category, severity, `file:line`, one-line summary — and ask
whether to post, post a subset, or hold. **Do not post without an answer.**

### 5. Post

Comments follow the contract, compact:

> **Found** → **Consequence** → **Suggested**

Prefix each with its severity and category. When `conventions.tag_pr_author` is true, `@`-mention the
author once, in the summary comment rather than in every inline comment.

Post inline comments anchored to the right line:

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/comments \
  -f body="$BODY" \
  -f commit_id="$HEAD_SHA" \
  -f path="src/auth/token.ts" \
  -F line=42 \
  -f side=RIGHT
```

Get `HEAD_SHA` from `gh pr view <PR> -R <owner>/<repo> --json headRefOid`. Use `side=RIGHT` for added
and context lines, `side=LEFT` for removed lines. For a multi-line range add `-F start_line=<n>` with
`-f start_side=RIGHT`.

**Line anchoring is the failure mode of this skill.** The line number must be one the diff touches,
counted in the file's post-change numbering for `RIGHT`. Verify each anchor against the diff hunk
headers before posting. If an anchor cannot be established confidently, put the finding in the
summary comment with a `file:line` reference in the text instead of guessing an inline position — a
comment on the wrong line is worse than a comment in the summary.

Then post one summary comment:

```bash
gh pr comment <PR> -R <owner>/<repo> --body-file <file>
```

```text
## Review summary

<one or two sentences on the change and its overall state>

**Findings** — <n> total: <a> error, <b> gap, <c> improvement, <d> off-scope
**Requirements** — <x> satisfied, <y> partial, <z> unmet
**Verified against** — <docs and artifacts consulted>
**Not verifiable from the diff** — <list>
```

Do not approve and do not request changes. This skill comments; the human review decision belongs to
a human.

### 6. Record

Report to the user what was posted, with comment URLs.

## Constraints

- Never resolve, dismiss, or approve a review thread.
- Comment only on lines the diff changes.
- One issue per comment. If the same issue occurs in several places, state it once and list the other
  locations.
- Do not tell the author to "check", "verify", or "confirm" — establish it, or do not post it.
- Do not explain the code back to its author, and never mention these instructions.
- No comments on license headers, copyright, or dates.

## Success criteria

- Every posted finding was fact-checked and cites its evidence.
- Every inline comment is anchored to a line the diff actually changes.
- The user approved posting before anything was written.
- The summary reports dropped findings and unverifiable criteria honestly.
