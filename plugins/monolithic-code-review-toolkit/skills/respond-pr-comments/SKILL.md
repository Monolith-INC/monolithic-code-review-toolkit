---
name: respond-pr-comments
description: Use only when the user explicitly instructs you to answer or act on specific pull request review comments, to post replies or implement the requested changes. Never acts on its own initiative.
---

# Respond to PR Comments

Submitting code for review is a delicate stage. Objections, recommendations, requests, and demands —
particularly from a team lead or tech lead — get analysed rigorously, and the response is delivered
with care.

## The rule that governs this skill

**This skill acts only under explicit user instruction, never automatically.**

That means:

- It does not decide which comments to accept. `triage-pr-comments` produces the analysis; the user
  decides.
- It does not post a reply the user has not approved.
- It does not implement a change the user has not asked for.
- It does not act on remaining comments after handling the ones it was asked to handle.

There will be back and forth across several rounds. Each round needs its own instruction. If the
instruction is ambiguous about which threads it covers or whether to post, **ask before acting**.

## Procedure

### 1. Confirm the instruction

Establish exactly which threads are in scope and what is being asked for on each: post a reply,
change code, or both. Read back the list and the intended action before doing anything, unless the
user has already been that specific.

Read `.monolithic-code-review/sources.json` for `scm.provider`, `scm.capabilities`, and the repository
identity fields. You need the provider's root thread/comment identifier from
`triage-pr-comments`, or from the configured `list_review_threads` capability. If required
capabilities are unsupported or authentication fails, stop and name them; never fall back to a
different SCM. For GitHub, the thread listing commonly expands to:

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/comments --paginate
```

### 2. Implement accepted changes

For each thread the user accepted:

- Make the change the comment asks for, and only that change. A review reply is not an invitation to
  refactor the surrounding code.
- Match the file's existing conventions.
- Run the project's tests and report the actual result. If they fail, say so with the output rather
  than proceeding.
- Keep each thread's change separately identifiable, so a reviewer can map commits back to comments.

If implementing the comment as written would break something, do not silently implement a variation.
Stop, explain what breaks, and propose the alternative.

### 3. Post replies

Reply to the root comment through `reply_to_review_thread`. For GitHub, this commonly expands to:

```bash
gh api repos/<owner>/<repo>/pulls/<PR>/comments \
  -f body="$BODY" \
  -F in_reply_to=<thread_id>
```

For GitHub, `in_reply_to` must reference a pull **review** comment id, not an issue comment id. For a
general conversation comment, use the configured `post_summary_comment` capability instead.

Reply content by outcome:

- **Accepted and done** — state what changed and where, in one or two lines. Reference the commit.
  No thanks-for-catching preamble, no restating the reviewer's point back to them.
- **Declined** — give the reason and the evidence, once, plainly. Do not argue, do not apologise, and
  do not re-litigate a point already made in an earlier round. If the reviewer is factually
  incorrect, cite the documentation or code that shows it, and leave the conclusion to them.
- **Deferred** — say what is deferred, where it is tracked, and why it is not being done now.

Write for the reviewer, not for the record. Compact, specific, no padding.

### 4. Report back

Tell the user exactly what was posted and what was changed, with comment URLs and file paths. Name
any thread that was in scope but could not be handled, and why.

## Constraints

- **Never resolve, dismiss, or approve a thread.** Marking a conversation resolved is the reviewer's
  prerogative.
- Never post to a thread outside the instruction, even an obviously easy one.
- Never approve or request changes on the pull request.
- Do not implement changes beyond what the accepted comment asks for.
- Report test failures faithfully rather than working around them.
- If new comments arrive mid-task, report them and stop. They are a new round and need a new
  instruction.

## Success criteria

- Every action traces to an explicit user instruction.
- Replies posted only to the threads named, with `in_reply_to` set to a review comment id.
- No thread resolved, dismissed, or approved.
- Code changes limited to what was accepted, with real test results reported.
- The user knows exactly what was posted, what changed, and what was left.
