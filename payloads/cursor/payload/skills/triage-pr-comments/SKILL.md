---
name: triage-pr-comments
description: Use when human reviewers have left comments on a pull request, to list every comment with its file and line, fact-check each one for accuracy and relevance, and present the results for the user to decide on.
---

# Triage PR Comments

Human reviewers are usually right and sometimes not. This skill collects every comment on a pull
request, fact-checks each one adversarially, and presents the results so the user can decide what to
accept and what to push back on.

This skill **decides nothing and posts nothing**. It produces the analysis; the user makes the call.
Acting on the outcome belongs to `respond-pr-comments`.

Requires `.monolithic-code-review/sources.json` and authenticated `gh`.

## Procedure

### 1. List every comment

Read `scm.owner` and `scm.repo` from the configuration and pass `-R <owner>/<repo>` to every call.

Prefer GraphQL, because it exposes resolved and outdated state that REST does not:

```bash
gh api graphql -f query='
query($owner:String!, $repo:String!, $number:Int!) {
  repository(owner:$owner, name:$repo) {
    pullRequest(number:$number) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          comments(first: 20) {
            nodes { databaseId body author { login } path line originalLine createdAt }
          }
        }
      }
    }
  }
}' -F owner=<owner> -F repo=<repo> -F number=<PR>
```

Map each thread: `thread_id` from the root comment's `databaseId`, `file` from `path`, `line` from
`line` falling back to `originalLine`, `reviewer` from the root author, and the full comment chain as
context.

Skip threads where `isResolved` or `isOutdated` is true, and report how many you skipped.

If GraphQL fails, fall back to REST and **keep only roots** — comments where `in_reply_to_id` is null.
Without that filter every reply is miscounted as a separate thread:

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/comments --paginate
```

Also collect general conversation comments, which carry no file anchor:

```bash
gh api repos/<owner>/<repo>/issues/<PR>/comments --paginate
```

Then get the diff, so each comment can be judged against what the code actually does:

```bash
gh pr diff <PR> -R <owner>/<repo>
```

### 2. Fact-check each comment adversarially

For every comment, establish what it actually claims, then test that claim. Read the code it points
at — the current content, not just the diff. Where the comment depends on library, framework, or API
behaviour, verify against current official documentation via Context7 or web search rather than
recall. Where it appeals to a project convention, find that convention in the repository and cite it,
or note that it is not written down anywhere.

Assign four attributes to each comment:

| Attribute        | Values                    | Meaning                                                                    |
| ---------------- | ------------------------- | --------------------------------------------------------------------------- |
| **Fact-check**   | `true` / `false`          | Is the factual claim correct? Cite the evidence either way.                  |
| **Suggestion**   | `accept` / `decline`      | Should the requested change be made?                                         |
| **Risk**         | `high` / `medium` / `low` | What is at stake if this comment is ignored?                                 |
| **Justification**| free text                 | Required whenever fact-check is `false` or suggestion is `decline`.          |

These are independent, and the interesting cases are where they diverge:

- **`true` + `decline`** — the reviewer is factually right, but the change is out of scope, or the
  cost outweighs the benefit. Justify it; this is the one the user most needs to see.
- **`false` + `accept`** — the stated reason is wrong but the underlying instinct is sound. Say what
  the real reason is.
- **`false` + `decline`** — needs the most careful justification, because it will be read as
  defensive. Cite evidence.

Risk reflects consequence, not tone. A politely-worded comment about an unhandled null in a payment
path is `high`. A strongly-worded comment about naming is `low`.

Weigh authority honestly but do not let it decide: a tech lead's objection raises the cost of
declining and the standard of justification required, but it does not make a false claim true. Note
the reviewer's role when the configuration or the user has established one.

### 3. Present for decision

Build a canvas — an artifact — as the primary output. It is a decision surface: the user needs to
scan every comment, see the four attributes at a glance, and click through to each thread.

Include per comment: reviewer, `file:line` (or `[general]`), the comment text, fact-check verdict with
evidence, suggestion verdict, risk, justification, and a link to the thread. Group by risk, highest
first. Lead with counts — total, accepted, declined, factually incorrect — and call out the
`true + decline` and `false + decline` cases, which are the ones needing a human decision.

Also print a compact terminal summary, so the user gets the shape of it without opening the canvas:

```text
## PR #<n> comment triage — <m> threads (<k> skipped: resolved/outdated)

accept <a> · decline <d> · fact-check false <f>

[high]   src/auth/token.ts:42   @reviewer   true  / accept   Expired token returned on renew failure
[medium] src/api/orders.ts:118  @lead       true  / decline  Out of scope — belongs to AGE-41
[low]    src/util/fmt.ts:7      @reviewer   false / decline  Claimed API deprecation; docs show current
```

Then stop and ask what the user wants to do. **Do not reply to any thread and do not change any code
from this skill.**

## Constraints

- Never resolve, dismiss, or approve a thread.
- Every `false` fact-check and every `decline` carries a justification with evidence.
- Do not soften a finding because of who wrote the comment, and do not sharpen one either.
- Report skipped resolved and outdated threads rather than silently dropping them.
- If a comment is ambiguous, say so and ask the user rather than guessing at intent.

## Success criteria

- Every unresolved thread appears exactly once, with its file and line.
- All four attributes assigned to every comment.
- Fact-checks cite evidence — documentation, code, or repository convention.
- Output is a canvas plus a terminal summary, and the skill ends by asking, not acting.
