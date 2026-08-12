---
name: review-setup
description: Use once per repository, before any other review skill, to record where requirements and definitions of done live and which pull-request host is in use. Run again when the tracker, remote, or vault layout changes.
---

# Review Setup

Every other skill in this toolkit needs two answers: **where do requirements live** and **where do
pull requests live**. This skill establishes both, confirms them with the user, and writes them to
`.monolithic-code-review/sources.json` in the repository being reviewed.

This toolkit names no tracker vendor. Which system holds requirements is the consuming repository's
business — Linear, Jira, Azure DevOps, YouTrack, GitHub issues, or plain files. Map whatever is
present onto the capability contract below.

## The capability contract

Three capabilities are all the review skills need:

| Capability                | Returns                                                           | Used by                          |
| ------------------------- | ----------------------------------------------------------------- | -------------------------------- |
| `fetch_work_item(id)`     | title, description, requirements, acceptance criteria / DoD        | every review skill               |
| `fetch_parent(id)`        | the parent item — task → story, story → feature                    | `review-feature`, scope checks   |
| `list_linked_artifacts(id)` | specs, design docs, attachments, linked URLs                     | post-flight fact-checking        |

A source satisfies the contract if it can answer all three. Partial sources are allowed — record what
is missing so dependent skills degrade honestly instead of inventing requirements.

## Procedure

### 1. Detect the pull-request host

```bash
git remote get-url origin
git branch --show-current
gh auth status
```

Parse `owner` and `repo` from the origin URL. This toolkit supports **GitHub** via the `gh` CLI. If
`origin` is not GitHub, stop and tell the user which host was found — do not guess an equivalent API.

If `gh auth status` fails, record the configuration anyway and warn that PR-side skills
(`review-story-postflight`, `triage-pr-comments`, `respond-pr-comments`) will not work until the user
runs `gh auth login`.

### 2. Enumerate what is actually available

Do not assume. Check, in this order, and report what you find:

1. **Tracker MCP tools in this session.** Look for tool names matching a tracker
   (`*linear*`, `*jira*`, `*azure*devops*`, `*youtrack*`, `*shortcut*`). Note the exact tool names —
   they are what gets recorded, not a vendor label.
2. **A local vault.** Look for `AI_Codex/`, `docs/specs/`, `.codex-workflows/`, `specs/`, or a
   comparable directory holding features, stories, or tickets. Read one file to learn the layout.
3. **GitHub issues**, if `gh` is authenticated — always available as a fallback.

### 3. Propose a mapping and confirm it

Present the candidate mapping to the user and **ask for confirmation before writing**. Show which
capability resolves to which concrete tool or path, and name anything you could not satisfy. If more
than one source is available, ask which is authoritative; a vault and a tracker often disagree, and
the user decides which wins.

### 4. Write the configuration

Write `.monolithic-code-review/sources.json` in the repository root:

```json
{
  "version": 1,
  "scm": {
    "provider": "github",
    "owner": "<owner>",
    "repo": "<repo>"
  },
  "tracker": {
    "kind": "mcp",
    "label": "Linear",
    "authoritative": true,
    "capabilities": {
      "fetch_work_item": "mcp__linear__get_issue",
      "fetch_parent": "mcp__linear__get_issue",
      "list_linked_artifacts": "mcp__linear__list_documents"
    },
    "scope": { "team": "AGE" },
    "unsupported": []
  },
  "vault": {
    "root": "AI_Codex",
    "features": "Features/",
    "stories": "Tickets/",
    "specs": "docs/specs/"
  },
  "conventions": {
    "tag_pr_author": true,
    "work_item_pattern": "AGE-\\d+"
  }
}
```

Field notes:

- `tracker.kind` — `mcp`, `cli`, `files`, or `none`.
- `tracker.capabilities` — concrete tool names or path templates, never vendor labels. A `files`
  tracker uses path templates such as `AI_Codex/Tickets/**/{id}*.md`.
- `tracker.unsupported` — capabilities this source cannot answer. Dependent skills must say so rather
  than proceed on assumption.
- `conventions.tag_pr_author` — whether posted PR comments `@`-mention the author. Ask the user;
  some teams consider it noise.
- `conventions.work_item_pattern` — regex for finding work-item ids in branch names and commit
  messages, so later skills can infer the item under review without being told.

Add `.monolithic-code-review/` to the repository's `.gitignore` unless the user wants the
configuration shared with the team. Ask.

### 5. Verify before declaring success

Resolve one real work item end to end through the recorded mapping and show the user the title and
acceptance criteria you got back. A configuration that has never successfully fetched anything is not
a working configuration.

## Provider recipes

Worked examples, not dependencies. An unlisted tracker works as long as the three capabilities
resolve to something.

| Source           | `fetch_work_item`                    | `fetch_parent`                          | `list_linked_artifacts`             |
| ---------------- | ------------------------------------ | --------------------------------------- | ----------------------------------- |
| Linear MCP       | `get_issue`                          | `get_issue` on `parent.id`; milestone for feature scope | `list_documents`, issue attachments |
| Jira MCP         | `getJiraIssue`                       | issue link of type *parent*             | remote links, attachments           |
| Azure DevOps MCP | `wit_get_work_item`                  | `System.Parent` relation                | work item `relations[]`             |
| YouTrack         | issue by id                          | `parent` link                           | issue attachments                   |
| GitHub issues    | `gh issue view <n> --json title,body` | parent from tracking checklist or label | links parsed from the issue body    |
| Local vault      | read `<stories>/**/{id}*.md`         | `feature:` frontmatter key              | `## Specs` links in the ledger      |

For file-backed sources, requirements and DoD are conventionally the `## Requirements` and
`## Definition of Done` sections. Record the actual heading names if the repository differs.

## Success criteria

- `.monolithic-code-review/sources.json` exists and parses.
- Every capability either resolves or is listed in `unsupported`.
- One real work item has been fetched and shown to the user.
- The user has confirmed the mapping and the `tag_pr_author` convention.
