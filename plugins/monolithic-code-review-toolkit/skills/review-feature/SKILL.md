---
name: review-feature
description: Use when a whole feature is complete, to run a rigorous adversarial review of the full feature diff against the feature's documented goal, definition of done and out-of-scope instructions. Optional flags: --lenses maintainability|typescript|all.
---

# Review Feature

The strictest gate in this toolkit. A feature is the unit the business actually asked for, so the
first question is not "is this code good" but **"is this diff in agreement with what the feature said
it would do"**.

Requires `.monolithic-code-review/sources.json`. If it is missing, run `review-setup` first.
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

For a feature under review as a pull request, execute the configured SCM capabilities
`get_pull_request` and `get_pull_request_diff` instead. If either is unsupported, report that and use
the local feature diff only after confirming the local refs represent the requested PR. For GitHub,
the mappings commonly expand to:

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

### 4. Build an attention-ordered change map when it earns its place

Before detailed findings, add a change map only when the feature diff has multiple responsibilities
or significant review noise: for example, it crosses core behavior and wiring, joins story seams
whose relationship affects correctness, or generated/mechanical churn could hide a material change.
Do not produce one for a single-responsibility, easy-to-follow diff merely because it touches
multiple files.

Order the map by reviewer attention, not diff order:

1. **Core behavior** — algorithms, state transitions, domain rules, public contracts, and the
   tests that establish them. Name the reviewer entry point and every relevant cross-story or
   cross-file relationship.
2. **Wiring and integration** — routes, dependency wiring, configuration, adapters, migrations, and
   their relationship to the core behavior they invoke or expose.
3. **Mechanical or generated** — formatting, renames, imports, generated files, and re-exports.
   List paths and statistics unless a concrete risk needs more context. Never call this group safe;
   it still needs proportionate review.

Use only the aid that removes a real comprehension barrier: pseudocode when syntax or nesting hides
the essential algorithm; a concrete before/after trace when the observable outcome is hard to
predict; and a labeled **Risk callout** only for a subtle, breaking, concurrent, security, or
performance-sensitive point. The map is an orientation aid, not a second diff or a finding list.


### Quality lens pass (when triggered)

After establishing the changed scope and before the final report, run each triggered quality lens
(see **Review flags and quality lenses** above). Requirements-first findings stay in their section;
lens-only `VERIFIED` findings go under the lens subsection.

### 5. Record evidence before reporting

For every material agreement verdict or candidate discrepancy, create an evidence record with an
`id`, falsifiable `claim`, `expected` requirement or invariant, decisive `evidence`, and, when
comparing states, same-measure `baseline` and `treatment`; include `confounds` when present.

| Verdict | Meaning | Disposition |
| --- | --- | --- |
| `VERIFIED` | Evidence supports the claim and meets its stated threshold. | `report` |
| `NOT VERIFIED` | Evidence contradicts the claim or misses its stated threshold. | `drop` |
| `INCONCLUSIVE` | Missing or invalid access, baseline, measurement, or environment prevents a decision. | `local-uncertainty` |

Category and severity remain independent. Only `VERIFIED` discrepancies become findings. Drop
`NOT VERIFIED` candidates. Keep `INCONCLUSIVE` claims under local uncertainty and never frame them
as findings or warnings.

### 6. Report

```text
## Feature review — <feature id>: <title>

<n> commits across <m> stories, <k> files, base <trunk>.

### Agreement
- Definition of done: <a>/<b> met
- Goal: met | partially met | not met — <one line>
- Out of scope: <n> violation(s)

VERDICT: in agreement | not in agreement — <reason>

### Change map
- **Core behavior** — `<entry path:line>` — reviewer entry point: <where to start>.
  Relationship: `<story or caller>` → `<domain rule>` → `<observable result>`.
- **Wiring and integration** — `<path>` — connects <migration, route, adapter, or configuration>
  to <core entry point>.
- **Mechanical or generated** — `<paths and statistics>` — <why it is present and any review risk>.

Include this section only when the trigger above is met. Omit empty groups and any unneeded
pseudocode, trace, or risk callout.

### Findings (severity order: critical, high, medium, low)
### [critical] gap — DoD item 4 "rollback path" is not implemented
**Found** — Migration db/migrations/014 has no down path.
**Consequence** — A failed rollout cannot be reverted without manual surgery on production data.
**Suggested** — Add the down migration, or amend the DoD if irreversibility is deliberate.
```

Lead with the agreement section and the verdict. Findings follow. Every finding carries
**Found → Consequence → Suggested** and a `file:line`.

Close with criteria **not verifiable from the diff**.

### 7. Apply the outcome

The brief for this stage expects the review to end in action. After reporting, ask the user which
findings to act on. Then, and only on their instruction:

- Post findings to the feature's pull request — hand off to `review-story-postflight`, which owns the
  posting mechanics.
- Address reviewer comments already on the pull request — hand off to `triage-pr-comments`, then
  `respond-pr-comments`.

Do not post or edit code from this skill without being asked to.

## Manual evaluation cases

- Supported claim: a feature DoD requires rollback, and the changed migration has no down path;
  cite the DoD and migration, mark `VERIFIED`, and report the `gap` with the existing three-part
  contract.
- Disproved claim: a suspected story seam mismatch is contradicted by both interface definitions
  and the integration test added by the feature; mark `NOT VERIFIED` and drop it.
- Inaccessible evidence: production observability required by the feature cannot be inspected in
  the available environment; mark `INCONCLUSIVE` with the missing access as a confound and retain
  it only as local uncertainty.
- Multi-layer fixture: one story changes entitlement rules, another wires a migration and API
  adapter, and the client is regenerated. Produce core → wiring → mechanical groups, identify the
  entitlement-to-adapter and migration relationships, and keep generated changes reviewable rather
  than safe by assumption; add a trace or labeled risk callout only if the behavior is genuinely
  hard to predict or subtle.
- Trivial fixture: a single localized validation fix with its focused test. Omit the map,
  pseudocode, before/after trace, and risk callout; keep any verified findings severity-ordered.

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
