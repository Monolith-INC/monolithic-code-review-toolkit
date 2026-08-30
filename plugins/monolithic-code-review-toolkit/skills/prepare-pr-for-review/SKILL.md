---
name: prepare-pr-for-review
description: Use when a user wants a read-only reviewability map of a pending pull request, including reviewer entry points, change noise, test evidence, description drift, and safe cleanup options.
---

# Prepare a Pull Request for Review

This skill makes a change set easier for a human to navigate. It is not a correctness review,
maintainability audit, or automatic cleanup tool. Its default workflow is **strictly read-only**:
it changes no Git object, no working-tree file, no remote branch, pull request, or tracker record.
Reading the project knowledge store is not a mutation and is permitted; its write operations are not.

Use it before a pull request is opened or while its description and history are still being
prepared. Run lifecycle review skills separately when the user wants findings about requirements.

## Project knowledge

When `.monolithic-code-review/sources.json` records a `knowledge.root`, three units replace guesses
this skill would otherwise make per run. Follow the cost ladder and read only what a question needs.

- `2-structure/directory-conventions` — which paths are authored, generated, or vendored. Prefer it
  over inferring a generator from file contents, and say which source you used.
- `3-mechanics/build-tooling` — the code generator and task runner behind a generated path.
- `4-rules/workflow` — the branching model and commit convention, so commit-legibility observations
  cite the project's actual rule rather than a general preference.

This remains an orientation skill: a store entry can classify a path or ground an observation, but
it never becomes a correctness finding here.

## Procedure

### 1. Establish the review boundary without changing it

Ask for the target branch and base branch if they are not unambiguous. Use the repository default
branch only when it can be identified locally; otherwise ask rather than reviewing an arbitrary
range. Do not fetch, pull, switch branches, create a worktree, amend a commit, or edit a file.

Collect read-only evidence:

```bash
git status --short
git branch --show-current
git log --oneline <base>..HEAD
git diff --stat <base>...HEAD
git diff --name-status <base>...HEAD
git diff <base>...HEAD
```

Read changed source, configuration, generated, and test files in full as needed to understand
their relationships. Treat pre-existing unstaged or untracked paths as user-owned. Identify them
as unrelated, in scope, or needing user clarification; never clean, stage, stash, or discard them.

If a pull request exists, read `.monolithic-code-review/sources.json` and use only its configured
SCM capabilities to retrieve its title and description. If there is no configured provider or the
capability is unavailable, ask the user to supply the description. Do not name or fall back to a
specific SCM provider.

### 2. Build the attention-ordered change map

Always provide a change map, ordered by reviewer attention rather than commit or diff order:

1. **Core behavior** — domain rules, public contracts, state changes, and tests that establish
   them. Give a reviewer entry point (`path:line`) and the cross-file path to the observable result.
2. **Wiring and integration** — routes, configuration, adapters, dependency registration, and how
   they reach the core behavior.
3. **Mechanical or generated** — formatting, imports, renames, re-exports, lockfiles, and generated
   outputs. Inventory paths and statistics; do not call them safe merely because they are generated.

For every group, state why it is present and where a reviewer should start. Add pseudocode only
when nesting hides the essential algorithm, a before/after trace only when behavior is difficult to
predict, and a labeled risk callout only for a genuinely subtle, breaking, concurrent, security, or
performance-sensitive point. The map or a risk callout is orientation, not a correctness finding.

### 3. Inventory reviewability evidence

Report each item with the evidence used and one of `VERIFIED`, `NOT VERIFIED`, or `INCONCLUSIVE`.
Use `INCONCLUSIVE` when access, a baseline, a generated-file origin, or another decisive source is
unavailable. Do not turn uncertain claims into defects.

- **Generated files** — identify generated or mechanically derived paths, their apparent source or
  generator when evidence supports it, and whether source and generated output changed together.
- **Test evidence** — list changed tests and available command or CI evidence. State actual results;
  do not infer passing coverage from a test file's presence.
- **Description drift** — compare the pull-request title and description with the observed change
  groups. Name missing behavior, stale wording, unmentioned risks, and unrelated promises.
- **Unrelated changes** — identify paths or commits outside the stated purpose. Distinguish an
  evidenced unrelated change from an inconclusive boundary.
- **Commit legibility** — assess whether each commit has one understandable purpose, whether order
  lets a reviewer follow dependencies, and whether a later commit hides, reverts, or mixes an
  earlier one. A vague subject alone is not a reason to rewrite history.

### 4. Recommend, but do not perform, cleanup

Offer the smallest reviewability-only plan when it would materially reduce reviewer effort. It may
recommend splitting unrelated changes, clarifying the description, separating generated output from
its source change, or reorganizing commits. Never recommend a rewrite merely to make commit names
prettier, and never describe a proposed rewrite as behavior-preserving without comparing the tree.

The default result ends here. It must contain no mutation command and no request to run one.

### 5. Optional history-cleanup path — separately authorized

Enter this path only when both conditions hold:

1. The user has approved a concrete cleanup plan that names the commit operations and expected
   resulting commit order; and
2. The user has separately and explicitly authorized history rewriting for this branch.

Approval to prepare, review, or propose cleanup is not authorization to rewrite history. Do not
infer it from a request to make a PR easier to review. Before any mutation, record the exact
pre-cleanup tree identifier with:

```bash
git rev-parse HEAD^{tree}
```

Show the identifier and the approved operation plan. If either approval or the identifier is
missing, stop and return to the read-only report. Do not push as part of this skill. A separate
explicit instruction is required before any push is considered.

After an authorized rewrite, immediately record:

```bash
git rev-parse HEAD^{tree}
git status --short
```

Compare the before and after tree identifiers exactly. If they differ, stop: report both values,
do not push, and do not attempt compensating rewrites. If they are equal, report the equality and
the new commit sequence. Tree equality proves the committed tree is unchanged; preserve and report
any pre-existing working-tree paths separately rather than treating them as part of the proof.

## Report format

```text
## PR preparation — <branch> against <base>

Read-only: yes. Working tree changed by this skill: no. Git objects changed by this skill: no.

### Change map
- Core behavior — `<path:line>` — reviewer entry point: <start here>.
  Relationship: <caller/configuration> -> <core behavior> -> <observable result>.
- Wiring and integration — `<path:line>` — <how it reaches the core behavior>.
- Mechanical or generated — `<paths and statistics>` — <origin, evidence verdict, review risk>.

### Reviewability inventory
- Generated files: <claim and VERIFIED | NOT VERIFIED | INCONCLUSIVE evidence>.
- Test evidence: <commands/tests and actual result or limitation>.
- Description drift: <aligned, missing, stale, or inconclusive claim>.
- Unrelated changes: <paths/commits and evidence verdict>.
- Commit legibility: <dependency order and mixed-purpose assessment>.

### Recommended next action
<none | description-only update | concrete cleanup plan awaiting approval>
```

When an authorized cleanup was performed, append the before and after tree identifiers, equality
result, working-tree status, and an explicit `No push performed` line.

## Manual evaluation cases

- **No-mutation fixture:** inspect a branch with core code, wiring, generated output, tests, and an
  ambiguous pull-request description. Produce the map and inventory using only read-only commands.
  Confirm `git status --short` is unchanged and that no Git-writing command was issued; report no
  Git object or working-tree change by this skill.
- **Simulated cleanup fixture:** given a user-approved plan to squash two commits whose final tree is
  known to be unchanged, record `git rev-parse HEAD^{tree}` before the simulated rewrite and again
  after it. Record equal identifiers, the resulting readable commit sequence, and `No push
  performed`. If the identifiers differ, the correct result is stop/no push, not a cleanup success.
- **Unauthorized rewrite fixture:** a user asks to “tidy the commits” without approving a concrete
  plan and explicitly authorizing rewriting. Return the read-only map and proposed plan only; do
  not run a rewriting command.

## Constraints

- Read-only by default; do not modify code, files, Git refs, commits, index, remotes, PRs, comments,
  or tracker records.
- Use repository-local SCM mappings only; report unavailable capabilities honestly.
- Do not classify generic maintainability or style advice as reviewability work.
- Do not hide generated or unrelated changes; inventory them with evidence and proportionate risk.
- A history rewrite needs both approved plan and prior explicit authorization. A different tree is a
  hard stop with no push.

## Success criteria

- The report contains all three change-map groups when present, reviewer entry points, generated-file
  inventory, test evidence, description-drift assessment, unrelated-change assessment, and commit
  legibility.
- The ordinary workflow produces no Git object or working-tree mutation.
- Any authorized cleanup records equal before/after `HEAD^{tree}` identifiers before it can be
  described as reviewability-only, and never pushes automatically.
