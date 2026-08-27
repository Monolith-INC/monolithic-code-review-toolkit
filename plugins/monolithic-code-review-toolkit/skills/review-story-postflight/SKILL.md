---
name: review-story-postflight
description: Use after a pull request has been opened for a user story, to run an adversarial review of the remote diff against the story specs and post categorized review comments to the pull request. Optional flags: --lenses maintainability|typescript|all.
---

# Review Story — Post-flight

An adversarial review of the **remote pull request diff**, fact-checked against the story's own
artifacts and against current official documentation, then posted to the pull request as review
comments.

This skill **writes to the pull request**. Confirm with the user before posting.

Requires `.monolithic-code-review/sources.json` and authenticated tooling for its configured SCM
provider.
## Review flags and quality lenses

User-invoked lifecycle reviews accept optional flags in the request:

| Flag | Effect |
| --- | --- |
| `--lenses maintainability` | Run the maintainability lens on the changed scope before reporting. |
| `--lenses typescript` | Force the TypeScript lens even when it would not otherwise trigger. |
| `--lenses all` | Run both maintainability and TypeScript lenses. |

Parse these flags from the user's message. Maintainability never runs without an explicit flag.
TypeScript runs when mandatory by configuration, when the changed scope includes `.ts` or `.tsx`
files, or when forced by flag.

Read `quality_lenses` from `.monolithic-code-review/sources.json` when present. After
`review-setup`, TypeScript repositories record `quality_lenses.typescript: "mandatory"`.

| Lens | Runs when |
| --- | --- |
| **TypeScript** | `quality_lenses.typescript` is `mandatory`, **or** the changed scope includes any `.ts`/`.tsx` file, **or** the user passed `--lenses typescript` or `--lenses all`. |
| **Maintainability** | The user passed `--lenses maintainability` or `--lenses all` only. |

When a lens triggers, execute the full read-only procedure from the matching skill
(`review-typescript` or `review-maintainability`) on the **same changed scope** as this review.
Merge only `VERIFIED` lens findings into this report under `### Quality lens — TypeScript` or
`### Quality lens — Maintainability`. Use the same evidence verdicts. Do not duplicate a defect
already reported in the requirements section — keep the requirements finding and omit the lens copy.

Complete requirements-first analysis before lens passes unless a lens check is the smallest decisive
evidence for a requirement claim.


## Stance

Adversarial means assuming the change is wrong until the diff shows otherwise. Trace the logic
rather than reading it. Prefer the failing case over the happy path. A review that finds nothing is
a legitimate outcome, but it must be the result of having genuinely looked for failure.

It does **not** mean hostile, exhaustive, or nitpicking. Every posted comment costs the author
attention; spend it only where something is actually at stake.

## Procedure

### 1. Ingest

Read `.monolithic-code-review/sources.json` for `scm.provider`, `scm.capabilities`, the repository
identity fields, and `conventions.tag_pr_author`. Execute the recorded `get_pull_request` and
`get_pull_request_diff` mappings with the PR identifier. Keep the configured repository identity in
every call so a fork or multi-remote checkout cannot mix repositories. If either capability is
unsupported or authentication fails, stop and name that capability; never fall back to another SCM.

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

For every material candidate, create an evidence record with an `id`, falsifiable `claim`, expected
requirement or invariant, decisive `evidence`, and, for comparisons, same-measure `baseline` and
`treatment`; include `confounds` when present.

| Verdict | Meaning | Disposition |
| --- | --- | --- |
| `VERIFIED` | Evidence supports the claim and meets its stated threshold. | `report` |
| `NOT VERIFIED` | Evidence contradicts the claim or misses its stated threshold. | `drop` |
| `INCONCLUSIVE` | Missing or invalid access, baseline, measurement, or environment prevents a decision. | `local-uncertainty` |

Category and severity remain separate from evidence verdict. Only `VERIFIED` candidates survive to
the user confirmation and may become inline or summary pull-request findings. Drop `NOT VERIFIED`
claims. Keep `INCONCLUSIVE` claims only in the local uncertainty summary; never post them as
confirmed findings or soften them into warnings. State the dropped count and reason, and the local
uncertainty count — that shows what fact-checking could decide.

### 4. Build the local preview change map when it earns its place

Before detailed findings, prepare a change map only when the pull-request diff has multiple
responsibilities or significant review noise: for example, it crosses core behavior and wiring,
spans several layers whose relationship affects correctness, or generated/mechanical churn could
hide a material change. Do not add one for a single-responsibility, easy-to-follow diff merely
because it touches multiple files.

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


### Quality lens pass (when triggered)

After the change map and **before Step 5 (Confirm)**, run each triggered quality lens (see
**Review flags and quality lenses** above). Include lens-only `VERIFIED` findings in the local
preview under `### Quality lens — TypeScript` or `### Quality lens — Maintainability`. Only
`VERIFIED` claims may be posted; lens findings follow the same rule as requirements findings.

### 5. Confirm with the user

Show the surviving findings — requirements and any lens findings — as a table: category, severity,
`file:line`, one-line summary, and source (requirements or lens name). Ask whether to post, post a
subset, or hold. When produced, show the change map first. Keep actual
findings severity-ordered: critical, high, medium, then low. **Do not post without an answer.**

### 6. Post

Comments follow the contract, compact:

> **Found** → **Consequence** → **Suggested**

Prefix each with its severity and category. When `conventions.tag_pr_author` is true, `@`-mention the
author once, in the summary comment rather than in every inline comment.

Post inline comments through the recorded `post_inline_comment` capability, anchored to the changed
line using the provider's line/thread model. For GitHub, the mapping will typically expand to:

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/comments \
  -f body="$BODY" \
  -f commit_id="$HEAD_SHA" \
  -f path="src/auth/token.ts" \
  -F line=42 \
  -f side=RIGHT
```

For GitHub, get `HEAD_SHA` from the configured PR metadata command. Use `side=RIGHT` for added
and context lines, `side=LEFT` for removed lines. For a multi-line range add `-F start_line=<n>` with
`-f start_side=RIGHT`.

**Line anchoring is the failure mode of this skill.** The line number must be one the diff touches,
counted in the file's post-change numbering for `RIGHT`. Verify each anchor against the diff hunk
headers before posting. If an anchor cannot be established confidently, put the finding in the
summary comment with a `file:line` reference in the text instead of guessing an inline position — a
comment on the wrong line is worse than a comment in the summary.

Then post one summary comment through `post_summary_comment`. For GitHub this is typically:

```bash
gh pr comment <PR> -R <owner>/<repo> --body-file <file>
```

```text
## Review summary

<one or two sentences on the change and its overall state>

### Change map
- **Core behavior** — `<entry path:line>` — reviewer entry point: <where to start>.
  Relationship: `<caller>` → `<domain rule>` → `<observable result>`.
- **Wiring and integration** — `<path>` — connects <dependency or route> to <core entry point>.
- **Mechanical or generated** — `<paths and statistics>` — <why it is present and any review risk>.

Include this section only when the trigger above is met. Omit empty groups and any unneeded
pseudocode, trace, or risk callout.

**Findings** — <n> total: <a> error, <b> gap, <c> improvement, <d> off-scope
**Requirements** — <x> satisfied, <y> partial, <z> unmet
**Verified against** — <docs and artifacts consulted>
**Not verifiable from the diff** — <list>
```

Do not approve and do not request changes. This skill comments; the human review decision belongs to
a human.

Keep the summary's detailed findings in severity order: critical, high, medium, then low. Do not
put the map in inline comments.


### 7. Record

Report to the user what was posted, with comment URLs.

## Manual evaluation cases

- Supported claim: the changed retry path returns success after a documented API error and a caller
  treats it as completion; cite the changed line, caller, and official API contract, mark
  `VERIFIED`, then offer the finding for user-approved posting.
- Disproved claim: a suspected framework regression is contradicted by current official docs and
  the actual call site; mark `NOT VERIFIED` and do not show or post it as a finding.
- Inaccessible evidence: a production-only integration behavior cannot be measured from the PR or
  available environment; mark `INCONCLUSIVE`, retain it only in the local uncertainty summary, and
  never include it in the posting table or pull-request comments.
- Multi-layer fixture: a domain retry policy, the caller that wires it, and a regenerated API client
  change together. Show core → wiring → mechanical in the local preview and summary, identify the
  caller-to-policy relationship, and treat a stale generated contract as reviewable risk only when
  evidence supports it; never label generated output safe.
- Trivial fixture: one null guard and its focused test change. Omit the map, pseudocode,
  before/after trace, and risk callout; present any verified finding in severity order.

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
