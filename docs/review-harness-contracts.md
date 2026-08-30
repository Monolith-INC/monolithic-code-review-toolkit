# Review Harness Contracts

The review harness is product infrastructure, not a Claude or Codex feature.
Its types, state transitions and capability meanings live in
`core/review_harness`; adapters only translate their host payloads and render
their host configuration.

## Sources v2

`.monolithic-code-review/sources.json` version 2 is the authoritative binding
document for a reviewed repository. A capability is an object, never a free-form
tool name or shell fragment. It has one of these forms:

| Kind | Required fields | Use |
| --- | --- | --- |
| `mcp_tool` | `server`, `tool`, `access`, `effect` | A host MCP endpoint |
| `command` | `program`, `args`, `access`, `effect` | An argv template with bounded placeholders |
| `path` | `path`, `access`, `effect` | A repository-relative read source |

Logical capability, access and effect are fixed by the core registry. For
example, `post_inline_comment` always has `write` access and the
`scm.comment.create` effect. An adapter cannot relabel it as read-only.

Version 1 remains readable during this compatibility release. The migration
helper converts exact `mcp__server__tool` references and unambiguous argv-like
commands. It refuses pipes, shell composition and malformed mappings; rerun
`review-setup` for those rather than guessing.

## Deterministic posting gate

The gate evaluates a normalized event against a checkpoint bound to the
workspace, repository, pull request and binding digest. A write is allowed only
when it identifies approved findings, is made by the poster where host identity
is available, and has not already been attempted. The hook records that attempt
before the host performs the write, deliberately preferring an explicit skipped
finding over a duplicate comment.

The gate is inert for actions without MCRT provenance. During an MCRT run,
malformed checkpoints, mismatched targets, unknown bindings, missing finding
ids and stale binding digests are denied. Recovery is explicit: inspect,
resume, abandon, or record the post outcome. No timeout silently grants or
removes an approval.

## Adapter conformance

Both adapters must map their PreToolUse payload into the same event fields:
workspace, repository, pull-request id, binding digest, actor role, finding ids
and optional host session/tool-use identity. The shared conformance fixtures
assert the same allow/deny result for Claude and Codex.

Claude retains its main-session skill for user questions. Codex installs an
`mcrt-review` entry skill plus custom agents. Both installs resolve project
bindings at runtime; user-level installation never bakes one project’s provider
tool names into another project’s agent definitions.
