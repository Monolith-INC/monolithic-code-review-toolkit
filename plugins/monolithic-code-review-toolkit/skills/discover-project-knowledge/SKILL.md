---
name: discover-project-knowledge
description: Use to build or refresh the project knowledge store that review skills read — a file-shaped index of what a repository is, how it is built, and how it is allowed to change. Invoked by review-setup on first configuration, and standalone whenever the project has moved on enough that reviews are citing stale facts.
---

# Discover Project Knowledge

Review skills measure a diff against **what the work asked for**. That leaves a second question they
cannot answer from the tracker: **what does this project already require of any change?** Layering
rules, mandated patterns, the real test command, which paths are generated — none of it lives in a
work item, and re-deriving it on every review is both expensive and inconsistent.

This skill writes it down once, in a form built for retrieval rather than for reading end to end.

It changes no source code. It writes only inside the configured knowledge root.

Requires `knowledge.root` in `.monolithic-code-review/sources.json`. If it is missing, run
`review-setup` first — that is where the store's location is chosen and recorded.

## What a good store is

Five properties, in priority order. Every rule below serves one of them.

1. **Progressive disclosure.** Manifest, then routing table, then unit. A reader never has to load
   the corpus to find one fact.
2. **One fact, one home.** Duplication is the main source of contradictory answers. A fact lives in
   exactly one unit; everything else links to it.
3. **Stable ids.** A rename breaks every cached reference and every backlink. Ids are paths, and
   paths do not change once written.
4. **Self-describing units.** Every unit states what it covers and when to read it, so the routing
   table can be trusted without opening anything.
5. **Lexically addressable.** Path plus grep answers first. The tree is deterministic precisely so
   that retrieval has a verifiable failure mode.

## The taxonomy

Five tiers. The number is the directory prefix, so lexical path order is tier order.

### Tier 1 — Identity: why it exists

Purpose, domain, business capability, and lifecycle stage (greenfield, maintenance, sunset).
Consumers: who calls this, who depends on it, what service levels are owed. Ownership: maintainers,
`CODEOWNERS`, and the escalation path when something breaks.

### Tier 2 — Structure: what is inside

Topology (single repository or one of many, package and module graph, entry points). Directory
conventions, and which paths are authored versus generated versus vendored. Domain model: the
ubiquitous language, core entities, invariants, bounded contexts. Architecture: layers, dependency
rules, key abstractions, and an index of decision records.

### Tier 3 — Mechanics: how it runs

Stack (languages, runtime and SDK versions, frameworks, lockfile state). Dependencies: direct
versus transitive, freshness, licences, upgrade policy. Build and tooling: task runner, code
generation, linters and analyzers, local bootstrap. Testing: the shape of the pyramid, frameworks,
fixtures and mocks, coverage gates, known flakiness. Data: schemas, migrations, seeds, caching,
external APIs. Contracts: the public API surface, OpenAPI, protobuf or event schemas, and the
compatibility policy. Runtime operations: environments, configuration and secrets, feature flags,
CI/CD, release and versioning, observability, runbooks.

### Tier 4 — Rules: how it is changed

Coding standards, prohibited and mandated patterns, how style is enforced. Branching model, commit
convention, pull-request and review gates, definition of done. Security and compliance: the
authentication and authorization model, secret handling, scanning, regulatory constraints.
Non-functional budgets: performance, offline behaviour, platform targets, internationalisation,
accessibility.

### Tier 5 — Evolution: where it is going

Git history signals: churn hotspots, complexity hotspots, bus-factor concentration. The tech-debt
registry, deprecated zones, in-flight migrations. Health metrics: CI pass rate, build time, coverage
trend, issue and pull-request ageing. Risks: manual steps, single points of failure, fragile
modules.

## Derivation split

This split decides what the skill may write on its own and what it must ask about.

| Source | Tiers | How it is established |
| --- | --- | --- |
| **Machine-derivable** | Tier 2 structure, Tier 3 mechanics, Tier 5 metrics | Read out of the tree, the manifests, and `git log` |
| **Human-authored only** | Tier 1 purpose and ownership, Tier 4 rationale, domain invariants, debt intent, risk judgement | Ask, or quote an authored document |

Most repositories have Tiers 2 and 3 inferable from the tree while Tier 1 and the *reasoning* behind
Tier 4 stay tribal knowledge. That is exactly where a written store earns its keep — and exactly
where invention is most damaging, because a fabricated rule posted to a pull request is
indistinguishable from a real one.

Every unit therefore carries a `provenance`:

| `provenance` | Meaning | May a review cite it as a project rule? |
| --- | --- | --- |
| `derived` | Read out of the tree; `sources` names the files it came from | Yes |
| `stated` | A human said it, or it is quoted from an authored document | Yes |
| `assumed` | Inferred, with no decisive evidence | No — it is `INCONCLUSIVE` by construction |

Never promote `assumed` to `derived` because the inference felt strong. An unsupported guess that
looks like a rule is the failure this field exists to prevent.

## The store layout

```text
<knowledge.root>/
  manifest.md                   store header: schema version, derived_from_commit, tiers present
  catalog.tsv                   routing table: id, type, area, title, path, updated, provenance, summary
  1-identity/
    purpose.md  consumers.md  ownership.md
  2-structure/
    topology.md  directory-conventions.md  domain-model.md  architecture.md  adr-index.tsv
  3-mechanics/
    stack.md  dependencies.tsv  build-tooling.md  testing.md  data.md  contracts.md  runtime-ops.md
  4-rules/
    coding-standards.md  workflow.md  security-compliance.md  nfr-budgets.md
  5-evolution/
    hotspots.tsv  tech-debt.md  health.tsv  risks.md
```

Format follows data shape, not preference:

| Shape | Format | Why |
| --- | --- | --- |
| Rationale, decisions, prose, rules | Markdown with YAML frontmatter | Headings are stable anchors; prose is what the reader needs |
| Uniform records, roughly 20 rows or more | TSV | Lowest token cost per fact, trivially parseable |
| Graph traversal | `[[id]]` link lines inside units | Traversal becomes reading rather than querying |

Do not add units the repository does not justify. An empty `data.md` costs a routing-table row and
returns nothing; omit it and record the omission in `manifest.md` instead.

## Unit schema

Every Markdown unit opens with this frontmatter. Order the keys as shown so units diff cleanly.

```yaml
---
id: 3-mechanics/testing
tier: 3
type: mechanics
area: testing
title: Testing
read_when: "Deciding whether a change needs a test, or which fixture pattern to follow."
provenance: derived
sources:
  - package.json
  - vitest.config.ts
  - .github/workflows/ci.yml
derived_from_commit: 42d900b
updated: 2026-08-30
version: 1
status: current
supersedes: []
links:
  - "[[3-mechanics/build-tooling]]"
---
```

| Key | Contract |
| --- | --- |
| `id` | The path under the knowledge root, without the extension. Stable for the life of the store |
| `tier` | 1 to 5, matching the directory prefix |
| `type` | `identity`, `structure`, `mechanics`, `rules`, or `evolution` — a retrieval facet |
| `area` | Narrower facet within the tier, such as `testing` or `ownership` |
| `read_when` | One sentence naming the decision this unit serves. This is what the routing table shows |
| `provenance` | `derived`, `stated`, or `assumed`, per the table above |
| `sources` | Repository paths the facts came from. Drives staleness — an empty list means nothing can invalidate this unit automatically |
| `derived_from_commit` | The commit the derivation read |
| `updated` | ISO date of the last write |
| `version` | Integer, incremented on every write. Concurrency token for the write operations |
| `status` | `current`, `deprecated`, or `superseded` |
| `supersedes` | Ids this unit replaced, empty when it replaced nothing |
| `links` | Outbound `[[id]]` references. Backlinks are derived from these, never hand-maintained |

`read_when` is the highest-value field in the schema. It is what lets a reader choose a unit from
the routing table without opening it, which is the whole point of the ladder.

A TSV unit carries the same fields as leading `#` comment lines before its header row, in
`# key: value` form, with list values comma-separated:

```text
# id: 3-mechanics/dependencies
# tier: 3
# type: mechanics
# area: dependencies
# read_when: Checking whether a package is already available before adding one.
# provenance: derived
# sources: package.json, pnpm-lock.yaml
# updated: 2026-08-30
# version: 1
# status: current
name	version	kind
```

Body headings are fixed per `type`, so an anchor fetch is predictable rather than exploratory:

| `type` | Required headings |
| --- | --- |
| `identity` | `## Summary`, `## Detail`, `## Open questions` |
| `structure` | `## Summary`, `## Layout`, `## Rules`, `## Open questions` |
| `mechanics` | `## Summary`, `## Commands`, `## Detail`, `## Open questions` |
| `rules` | `## Summary`, `## Mandated`, `## Prohibited`, `## Enforcement`, `## Open questions` |
| `evolution` | `## Summary`, `## Signals`, `## Detail`, `## Open questions` |

`## Open questions` is never dropped. An empty one reads `- none`; it is where a reader learns what
the store does not know, which is as useful as what it does.

## Procedure

### 1. Resolve the root and decide build or refresh

Read `knowledge.root` from `.monolithic-code-review/sources.json`. If the key is absent, stop and
say that `review-setup` has not configured a store yet.

If `manifest.md` exists, this is a **refresh** — go to step 5. Otherwise it is a first build.

### 2. Derive Tiers 2, 3 and 5

Read-only inspection only. Work from evidence that is actually present; record what you could not
find rather than filling the gap.

- **Tier 2** — the directory tree, entry points, workspace and package manifests, import graphs at
  the module level, generated-file markers (`@generated`, codegen configuration, lockfiles), vendor
  directories, and any decision-record directory.
- **Tier 3** — language and runtime manifests, lockfiles, task runners, linter and formatter
  configuration, test configuration and helpers, CI workflows, migration and schema directories,
  API contract files, deployment and environment configuration.
- **Tier 5** — `git log` for churn and hotspot concentration, author distribution per path for bus
  factor, and any health signal the repository records itself.

Useful starting points, none of them assumed to exist:

```bash
git log --format='%H' -1
git log --since='12 months ago' --name-only --format= | sort | uniq -c | sort -rn | head -40
git log --since='12 months ago' --format='%an' | sort | uniq -c | sort -rn
```

Record every fact with the file it came from. A Tier 3 claim with no `sources` entry is an
`assumed` claim wearing a `derived` label.

### 3. Interview for Tiers 1 and 4

Present what the tree suggests, then ask. Do not write Tier 1 or the rationale behind Tier 4 from
inference alone.

Ask about, at minimum: what this project is for and who consumes it; lifecycle stage; who owns it
and how an incident escalates; which patterns are mandated or prohibited and why; the review gates
and definition of done; any regulatory or security constraint a reviewer must respect; and the
non-functional budgets a change can violate.

Where an authored document already answers one — a contributing guide, an agent instruction file, a
decision record, a runbook — quote it and record `provenance: stated` with that document in
`sources`. That is stronger than an interview answer, because it survives the person.

Where the user does not know or does not answer, write the unit with the honest gap under
`## Open questions` and leave the claim out. **Never** convert an unanswered question into an
`assumed` rule.

### 4. Write the store

Write `manifest.md`, then the units, then regenerate `catalog.tsv` from the units' frontmatter so
the routing table can never disagree with what it routes to.

`catalog.tsv` is tab-separated with a header row:

```text
id	type	area	title	path	provenance	updated	read_when
```

Sort by `id` so the file is byte-stable across regenerations and diffs stay legible.

`manifest.md` records the store schema version, `derived_from_commit`, which tiers are present,
which units were deliberately omitted and why, and the count of units by provenance. A reader who
opens only the manifest should learn how much of the store to trust.

### 5. Refresh incrementally

A refresh must not rewrite units whose inputs did not move. Rewriting everything destroys the
`updated` signal and buries the human-authored content in churn.

1. Read `derived_from_commit` from `manifest.md`.
2. `git diff --name-only <derived_from_commit>...HEAD` gives the changed paths.
3. A unit is **stale** when any changed path matches an entry in its `sources`.
4. Re-derive stale units only. Leave the rest byte-identical, including their `updated` dates.
5. A unit whose `provenance` is `stated` is **never** overwritten automatically. Flag it as
   possibly stale, say which changed path suggests it, and ask. A machine cannot re-derive a human
   judgement, and silently replacing one with an inference is how a store starts lying.
6. Regenerate `catalog.tsv` and update `manifest.md` with the new commit.

If `derived_from_commit` is unreachable — history rewritten, shallow clone — say so and treat the
run as a first build rather than diffing against a commit you cannot read.

### 6. Append and deprecate rather than rewrite

When a fact genuinely changes rather than being corrected, the old unit is history worth keeping.
Set its `status` to `superseded`, write the replacement, and list the old id in the replacement's
`supersedes`. Reviews read `status: current` by default, so superseded units cost a reader nothing
while remaining reachable.

Correcting a typo or a wrong derivation is an ordinary write — bump `version`, keep the id. Reserve
supersession for a change in the underlying truth.

## Reading the store

Retrieval is a cost ladder. Skills that consume the store follow it in order, and this skill writes
the store so that the ladder works:

| Step | Call | Rough cost | Returns |
| --- | --- | --- | --- |
| 1 | `catalog` | ~200 tokens | Routing table — `read_when` and facets, never content |
| 2 | `find` | ~500 tokens | Locations with `matched_terms` and a snippet, never whole units |
| 3 | `fetch` | ~800 tokens | One unit or one anchor, with its `version` token |

Where the knowledge MCP adapter is installed, these are the `knowledge_catalog`, `knowledge_find`
and `knowledge_fetch` tools. Where it is not, the layout is deterministic, so reading `catalog.tsv`,
then grepping the tree, then reading one file satisfies the same ladder with no tooling at all. That
fallback is a design requirement, not a degradation: the store is lexically addressable first and
semantically addressable never.

## Manual evaluation cases

- A repository with a lockfile, a task runner and CI workflows: Tiers 2 and 3 are written
  `derived`, each unit naming the manifest it read. No interview is needed for them.
- The user cannot say who owns the service. Write `1-identity/ownership.md` with the `CODEOWNERS`
  entries as `derived` facts and the escalation path listed under `## Open questions`. Do not invent
  an escalation path.
- A contributing guide states the commit convention. Record it in `4-rules/workflow.md` as
  `stated` with the guide in `sources`, not as `derived` — a human wrote that rule, and the
  distinction is what lets a review cite it.
- A refresh after a one-file commit that touched only a test helper: exactly the units listing that
  path in `sources` are re-derived. Every other unit keeps its `updated` date.
- The team replaces its ORM. The old `3-mechanics/data.md` becomes `status: superseded` and the new
  unit lists it in `supersedes`, so a reviewer reading a year-old pull request can still see what
  was true then.
- A monorepo with three deployable applications: write per-application units under the tier
  directories with the application in `area`, rather than one averaged unit that is true of none of
  them.

## Constraints

- Write only inside `knowledge.root`. This skill never edits source, configuration, Git state,
  remotes, pull requests, comments, or tracker records.
- Never write a Tier 1 or Tier 4 rule from inference. Ask, quote an authored document, or leave it
  under `## Open questions`.
- Every `derived` claim names the file it came from in `sources`. No `sources`, no `derived`.
- Ids are stable. Correct a unit in place; never rename one to a tidier path.
- One fact, one home. When two units would state the same thing, keep it in the more specific one
  and link from the other.
- No unit exceeds what a reader needs in one sitting. Split by `area` before letting a unit sprawl.
- A refresh rewrites only stale units, and never a `stated` one without asking.

## Success criteria

- `manifest.md` and `catalog.tsv` exist, parse, and agree with the units on disk.
- Every unit has complete frontmatter, the required headings for its `type`, and a non-empty
  `read_when`.
- Every `derived` unit names at least one path in `sources`; every `stated` unit names its document
  or records that it came from the user.
- No Tier 1 or Tier 4 rule was written from inference alone.
- The catalog is sorted by `id` and regenerating it produces no diff.
- A refresh run on an unchanged tree rewrites nothing.
