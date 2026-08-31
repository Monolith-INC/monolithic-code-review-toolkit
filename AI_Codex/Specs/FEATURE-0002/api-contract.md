---
type: api-contract
feature: FEATURE-0002
status: accepted
---

# API Contract — Review harness v1

## Schemas

`sources.json` v2 contains typed capability bindings. Every binding has a fixed
logical capability, access mode and effect. `mcp_tool` uses `{server, tool}`;
`command` uses `{program, args}`; `path` uses a bounded repository-relative
path. The checked-in schema snapshot is
`core/review_harness/schema/sources-v2.schema.json`.

A normalized action event contains MCRT provenance, workspace, repository, PR
id, binding digest, finding ids and optional role/session/tool-use identities.
A checkpoint binds those target fields and records approved, attempted and
outcome fields.

## Gate responses

The pure gate returns `{allowed, reason?, authorization_ids[]}`. A hook blocks
on `allowed: false`; a successful pre-hook authorization consumes its finding
ids. Unknown fields, target mismatches and repeated ids are denials.

## Compatibility

v1 reads are accepted during this compatibility release. v1 writes are not
eligible for automated posting. Migration is all-or-nothing and never rewrites
an ambiguous command string.
