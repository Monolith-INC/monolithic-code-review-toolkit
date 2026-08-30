# Knowledge MCP adapter

Serves a repository's **project knowledge store** — the file-shaped index written by
`monolithic-code-review-toolkit:discover-project-knowledge` — through a bounded MCP tool surface.

The portable skills remain the source of truth. This adapter is optional: the store's layout is
deterministic, so a host without it reaches the same facts with `catalog.tsv` plus `grep`. What the
adapter adds is ranking, backlinks, bounded output, and safe concurrent writes.

## Install

```bash
python3.12 -m pip install -e adapters/knowledge
python3.12 adapters/knowledge/install_knowledge_adapter.py --project /path/to/repository
```

The installer registers one stdio server named `mcrt-knowledge` in the project's `.mcp.json` and
points it at `knowledge.root` from `.monolithic-code-review/sources.json`. Pass `--knowledge-root`
to override, `--scope user` to register it for every repository, `--dry-run` to see the planned
edit, and `--uninstall` to remove it. Uninstalling never touches the store itself.

This is the only part of the toolkit with third-party Python dependencies (`mcp`, `pydantic`). The
portable plugin and the two review-orchestrator adapters still run from a checkout with nothing
installed — see [ADR-0006](../../AI_Codex/Architecture/ADR/ADR-0006-project-knowledge-store-and-lookup-contract.md).

## The tool surface

Four read tools and three write tools. Not five, and not a general `query(sql)` — an unbounded
query surface has no cost model and cannot be validated cheaply.

The read side is a **cost ladder**, and each tool's description says which rung it is. Without that,
agents start at the most expensive call and guess a path.

| Rung | Tool | Cost | Returns |
| --- | --- | --- | --- |
| 1 | `knowledge_catalog` | ~200 tokens | Routing table: id, type, area, provenance, `read_when`. **Never content** |
| 2 | `knowledge_find` | ~500 tokens | Locations: id, anchor, line range, score, `matched terms`, snippet |
| 3 | `knowledge_fetch` | ~800 tokens | One unit or one anchor, plus its version token |
| — | `knowledge_links` | small | Inbound and outbound edges for one unit |

| Tool | Requires | Notes |
| --- | --- | --- |
| `knowledge_put` | `if_version` | Whole-unit replace, or `new` to create |
| `knowledge_patch` | `if_version` | Replaces one exact occurrence — the preferred edit |
| `knowledge_add` | `if_version` | Appends; the store's contract is append-and-deprecate |

## Behaviours that matter

These are implemented, not merely documented, and each has a test.

- **`matched_terms` on every hit.** The agent can see that its query matched `tax` but not `MEI`
  and reformulate itself, with no human round trip.
- **Empty results return guidance.** Available facet values, near-miss terms that do exist, and the
  unit ids in scope. A zero-result response that teaches nothing costs a turn and earns nothing.
- **Errors are self-healing.** A version conflict returns the current content; a failed `patch`
  returns the surrounding text. Every failure carries what the retry needs, in the same turn.
- **Bounded output with explicit truncation.** Over-budget content returns a continuation handle.
  Silent truncation is how an agent confidently answers from half a document.
- **Deterministic ordering.** Score, then path, then anchor — repeat calls are reproducible and
  therefore cacheable.
- **Facets, not a DSL.** Fixed `type`, `area`, `status`, `path_prefix`, `updated_after` filters.
- **Optimistic concurrency.** Every `fetch` returns a content-addressed version token and every
  write requires one, so two writers cannot silently clobber each other.
- **Markdown responses.** JSON is reserved for the few fields a caller must parse.

## Provenance is the trust boundary

Every unit records how its facts were established, and the server surfaces it on every read:

| `provenance` | Meaning | Citable as a project rule? |
| --- | --- | --- |
| `derived` | Read out of the tree; `sources` names the files | Yes |
| `stated` | A human authored it, or it is quoted from an authored document | Yes |
| `assumed` | Inferred with no decisive evidence | No — `INCONCLUSIVE` by construction |

`knowledge_fetch` prefixes an `assumed` unit with that warning, because the expensive failure is a
review posting an inferred convention to a pull request as though a human had written it.

## Development

```bash
python3.12 -m unittest discover -s adapters/knowledge/tests -t .
```

The store layer (`knowledge_store.py`) is dependency-free and its tests always run. The MCP
contract tests skip when the SDK is absent, so a contributor without the adapter installed still
gets a meaningful suite; CI installs the dependencies, so the skip never hides a regression there.

Run the server directly to debug it:

```bash
MCRT_KNOWLEDGE_ROOT=/repo/.monolithic-code-review/knowledge \
  python3.12 adapters/knowledge/mcrt_knowledge_mcp.py
```
