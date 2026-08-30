#!/usr/bin/env python3.12
"""MCP server over a project knowledge store.

Four read tools and three write tools, no more. The read side is a cost ladder —
`knowledge_catalog` routes, `knowledge_find` locates, `knowledge_fetch` retrieves —
and every tool description says so, because a tool surface that does not state its
ladder gets entered at the most expensive rung with a guessed path.

Responses are the Markdown a model reads best. JSON is reserved for the few fields a
caller must parse: version tokens, line ranges, continuation handles.

Run it directly for stdio, pointing at a store:

    MCRT_KNOWLEDGE_ROOT=/repo/.monolithic-code-review/knowledge \
        python3.12 mcrt_knowledge_mcp.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_store import (  # noqa: E402  (the path shim above must run first)
    NEW_VERSION,
    KnowledgeStore,
    StoreError,
)

ROOT_ENV = "MCRT_KNOWLEDGE_ROOT"

#: Default ceiling for a single `knowledge_fetch`. A unit over it comes back truncated
#: with a continuation handle rather than silently clipped.
DEFAULT_MAX_TOKENS = 2000

UnitType = Literal["identity", "structure", "mechanics", "rules", "evolution"]
UnitStatus = Literal["current", "deprecated", "superseded"]

mcp = MCPServer(
    "mcrt_knowledge_mcp",
    instructions=(
        "Project knowledge for the repository under review: what it is, how it is built, and how "
        "it is allowed to change. The read side is a cost ladder — knowledge_catalog (~200 tokens) "
        "routes, knowledge_find (~500) locates, knowledge_fetch (~800) retrieves. Start at the "
        "catalog and never guess a unit id. Every write requires the version token a fetch returns. "
        "A unit's `provenance` decides how far it can be trusted: `derived` and `stated` may be "
        "cited as project rules, `assumed` may not."
    ),
)

_store: KnowledgeStore | None = None


def store() -> KnowledgeStore:
    global _store
    if _store is None:
        root = os.environ.get(ROOT_ENV)
        if not root:
            raise RuntimeError(
                f"{ROOT_ENV} is not set. Point it at the knowledge root recorded as "
                f"`knowledge.root` in .monolithic-code-review/sources.json."
            )
        _store = KnowledgeStore(root)
    return _store


def set_store(value: KnowledgeStore | None) -> None:
    """Test seam. Production resolves the root from the environment instead."""
    global _store
    _store = value


# ---------------------------------------------------------------------------
# Rendering — Markdown out, JSON only for what must be parsed
# ---------------------------------------------------------------------------

def _table(rows: list[dict[str, str]], columns: tuple[str, ...]) -> str:
    cells = [
        "| " + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in columns) + " |"
        for row in rows
    ]
    return "\n".join(
        ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |", *cells]
    )


def _error(exc: Exception) -> str:
    """Render a failure so the retry happens this turn, not the next one."""
    if not isinstance(exc, StoreError):
        return f"Error: {exc}"

    payload = exc.payload()
    lines = [f"Error ({payload['kind']}): {payload['message']}"]

    if payload["kind"] == "version_conflict" and payload.get("current_content"):
        lines += [
            "",
            f"Current version: `{payload['current_version']}`. Merge your change into the content "
            "below and retry with that token.",
            "",
            "```",
            payload["current_content"],
            "```",
        ]
    elif payload["kind"] == "patch_mismatch":
        lines += ["", "Text actually present around your anchor:", "", "```", payload["context"], "```"]
    elif payload["kind"] == "unknown_unit" and payload.get("nearest"):
        lines += ["", "Closest ids: " + ", ".join(f"`{item}`" for item in payload["nearest"])]
    return "\n".join(lines)


def _guidance(terms: str, guidance: dict[str, Any]) -> str:
    """A zero-result response that teaches nothing costs a turn and earns nothing."""
    lines = [
        f"No hits for `{terms}` — {guidance['reason']}.",
        "",
        f"The store holds {guidance['unit_count']} unit(s); "
        f"{guidance['candidates_after_filters']} passed your filters.",
    ]
    facets = guidance.get("facets", {})
    for name in ("type", "area", "status"):
        values = facets.get(name) or []
        if values:
            lines.append(f"- Available `{name}`: " + ", ".join(f"`{value}`" for value in values))
    if guidance.get("near_miss_terms"):
        lines.append("- Terms that do exist: " + ", ".join(f"`{term}`" for term in guidance["near_miss_terms"]))
    if guidance.get("nearest_units"):
        lines.append("- Units in scope: " + ", ".join(f"`{unit}`" for unit in guidance["nearest_units"]))
    return "\n".join(lines + ["", "Reformulate with one of the terms above, or widen the filters."])


def _written(action: str, result: dict[str, Any]) -> str:
    return (
        f"{action} `{result['id']}` ({result['path']}, {result['bytes']} bytes).\n"
        f"New version token: `{result['version']}` — pass it as `if_version` on your next write."
    )


# ---------------------------------------------------------------------------
# Read tools — the cost ladder
# ---------------------------------------------------------------------------

@mcp.tool(
    name="knowledge_catalog",
    annotations=ToolAnnotations(
        title="Catalog project knowledge",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def knowledge_catalog(
    path_prefix: Annotated[
        str | None, Field(default=None, description="Restrict to ids under this prefix, e.g. '4-rules'.")
    ] = None,
    type: Annotated[UnitType | None, Field(default=None, description="Restrict to one unit type.")] = None,
    updated_after: Annotated[
        str | None, Field(default=None, description="ISO date; keeps units updated strictly after it.")
    ] = None,
) -> str:
    """RUNG 1 OF 3, ~200 tokens. Start here. Routing table only — never content.

    Returns each unit's id, type, area, provenance and `read_when` — the decision that
    unit exists to serve — so you can choose the right one before spending anything.
    Call it once and reuse the result for the rest of the session.

    Then: `knowledge_find` (~500 tokens) to locate text inside units, and
    `knowledge_fetch` (~800 tokens) to read one. Do not start at fetch with a guessed
    id; ids come from here.
    """
    try:
        rows = store().catalog(path_prefix=path_prefix, type=type, updated_after=updated_after)
    except Exception as exc:  # noqa: BLE001 - every failure is returned as readable text
        return _error(exc)

    if not rows:
        return "The catalog is empty for those filters. Drop `path_prefix`/`type` to see the whole store."

    return "\n".join(
        [
            f"{len(rows)} unit(s). `provenance` decides citability: `derived` and `stated` may be "
            "cited as project rules, `assumed` may not.",
            "",
            _table(rows, ("id", "type", "area", "provenance", "updated", "read_when")),
            "",
            "Next: `knowledge_find` to locate text, then `knowledge_fetch` to read one unit.",
        ]
    )


@mcp.tool(
    name="knowledge_find",
    annotations=ToolAnnotations(
        title="Find project knowledge",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def knowledge_find(
    terms: Annotated[str, Field(description="Free-text terms, e.g. 'dependency direction layering'.")],
    path_prefix: Annotated[
        str | None, Field(default=None, description="Restrict to ids under this prefix.")
    ] = None,
    type: Annotated[UnitType | None, Field(default=None, description="Restrict to one unit type.")] = None,
    area: Annotated[str | None, Field(default=None, description="Restrict to one area, e.g. 'testing'.")] = None,
    status: Annotated[
        UnitStatus | None,
        Field(default="current", description="Defaults to 'current'. Pass null to search superseded history too."),
    ] = "current",
    limit: Annotated[int, Field(default=8, ge=1, le=50, description="Maximum hits to return.")] = 8,
) -> str:
    """RUNG 2 OF 3, ~500 tokens. Locations, not documents.

    Returns id, anchor, line range, score, matched terms and one snippet per hit.
    Read `matched terms` before anything else: if a term you cared about is missing,
    the query was wrong rather than the store, and reformulating costs far less than
    fetching the wrong unit.

    Ordering is deterministic, so repeat calls are reproducible. A query with no hits
    comes back with the facet values, near-miss terms and unit ids that do exist.

    Then: `knowledge_fetch` with the id and anchor of the hit you want.
    """
    try:
        hits, guidance = store().find(
            terms=terms, path_prefix=path_prefix, type=type, area=area, status=status, limit=limit
        )
    except Exception as exc:  # noqa: BLE001
        return _error(exc)

    if not hits:
        return _guidance(terms, guidance)

    lines = [f"{len(hits)} hit(s) for `{terms}`, best first.", ""]
    for hit in hits:
        anchor = f"#{hit.anchor}" if hit.anchor else ""
        lines += [
            f"### `{hit.unit_id}{anchor}` — {hit.title}",
            f"lines {hit.start_line}-{hit.end_line} · score {hit.score} · "
            f"matched terms: {', '.join(hit.matched_terms)}",
            f"> {hit.snippet}",
            "",
        ]
    return "\n".join(lines + ["Fetch one with `knowledge_fetch(id, anchor)` rather than reading the whole unit."])


@mcp.tool(
    name="knowledge_fetch",
    annotations=ToolAnnotations(
        title="Fetch a knowledge unit",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def knowledge_fetch(
    id: Annotated[str, Field(description="Unit id from catalog or find, e.g. '4-rules/coding-standards'.")],
    anchor: Annotated[
        str | None,
        Field(default=None, description="Heading slug from a find hit, e.g. 'mandated'. Cheapest way to read one rule."),
    ] = None,
    start_line: Annotated[int | None, Field(default=None, ge=1, description="1-indexed line to start at.")] = None,
    end_line: Annotated[int | None, Field(default=None, ge=1, description="1-indexed inclusive line to stop at.")] = None,
    max_tokens: Annotated[
        int,
        Field(default=DEFAULT_MAX_TOKENS, ge=50, le=20000, description="Hard ceiling; over-budget content truncates."),
    ] = DEFAULT_MAX_TOKENS,
) -> str:
    """RUNG 3 OF 3, ~800 tokens. One unit, or one anchor within it.

    Pass the `anchor` from a find hit to read a single heading instead of a whole unit.
    Output is capped: over-budget content is truncated explicitly and returns a
    continuation handle, never silently clipped.

    The version token in the response is what every write requires. Do not reach for
    this tool with a guessed id — get ids from `knowledge_catalog` or `knowledge_find`.
    """
    try:
        result = store().fetch(
            unit_id=id, anchor=anchor, start_line=start_line, end_line=end_line, max_tokens=max_tokens
        )
    except Exception as exc:  # noqa: BLE001
        return _error(exc)

    lines = [
        f"`{result['id']}`"
        + (f" · anchor `{result['anchor']}`" if result["anchor"] else "")
        + f" · version `{result['version']}` · provenance `{result['provenance']}`"
        + f" · status `{result['status']}` · updated {result['updated'] or 'unknown'}",
        "",
    ]
    if result["provenance"] == "assumed":
        lines += [
            "This unit is `assumed`: inferred with no decisive evidence. Treat it as INCONCLUSIVE — "
            "it cannot support a finding on its own.",
            "",
        ]
    lines.append(result["content"])
    if result["truncated"]:
        handle = result["continuation"]
        lines += [
            "",
            f"--- truncated at the token ceiling. {handle['remaining_lines']} line(s) remain. "
            f"Continue with start_line={handle['start_line']}.",
        ]
    return "\n".join(lines)


@mcp.tool(
    name="knowledge_links",
    annotations=ToolAnnotations(
        title="Traverse knowledge links",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def knowledge_links(
    id: Annotated[str, Field(description="Unit id whose edges you want.")],
    direction: Annotated[
        Literal["in", "out", "both"],
        Field(default="both", description="'in' for backlinks, 'out' for references this unit makes."),
    ] = "both",
) -> str:
    """Graph edges for one unit: what it references, and what references it.

    Backlinks cannot be found by grep, so this is the only way to discover which units
    depend on the one you are reading. Reach for it after `knowledge_fetch` when a rule
    looks like it has consequences elsewhere.
    """
    try:
        edges = store().links(id, direction)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)

    lines = [f"Links for `{id}`:"]
    if "out" in edges:
        lines.append("- references: " + (", ".join(f"`{item}`" for item in edges["out"]) or "none"))
        if edges.get("out_unresolved"):
            lines.append(
                "- unresolved references (target does not exist): "
                + ", ".join(f"`{item}`" for item in edges["out_unresolved"])
            )
    if "in" in edges:
        lines.append("- referenced by: " + (", ".join(f"`{item}`" for item in edges["in"]) or "none"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write tools — every one requires a version token
# ---------------------------------------------------------------------------

@mcp.tool(
    name="knowledge_put",
    annotations=ToolAnnotations(
        title="Create or replace a knowledge unit",
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def knowledge_put(
    id: Annotated[str, Field(description="Unit id to create or replace.")],
    content: Annotated[str, Field(description="The complete unit, frontmatter included.")],
    if_version: Annotated[
        str, Field(description=f"Version token from a prior fetch, or '{NEW_VERSION}' to create.")
    ],
) -> str:
    """Create a unit, or replace one wholesale.

    This replaces everything — prefer `knowledge_patch` for a targeted edit and
    `knowledge_add` to append. `if_version` must be the token from a prior
    `knowledge_fetch`, or the literal `new` to create a unit that does not exist yet.
    A stale token returns the current content so you can merge and retry in this turn.

    `version` and `updated` are stamped for you; do not hand-maintain them.
    """
    try:
        return _written("Wrote", store().put(id, content, if_version))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool(
    name="knowledge_patch",
    annotations=ToolAnnotations(
        title="Patch a knowledge unit",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def knowledge_patch(
    id: Annotated[str, Field(description="Unit id to edit.")],
    old: Annotated[str, Field(description="Exact text to replace. Must occur exactly once.")],
    new: Annotated[str, Field(description="Replacement text.")],
    if_version: Annotated[str, Field(description="Version token from a prior fetch.")],
) -> str:
    """Replace one exact occurrence of `old` with `new` — the surgical edit.

    Use it in preference to `knowledge_put` whenever you are changing part of a unit.
    `old` must occur exactly once; if it does not match, the surrounding text comes
    back so you can correct the anchor without re-fetching the unit.
    """
    try:
        return _written("Patched", store().patch(id, old, new, if_version))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool(
    name="knowledge_add",
    annotations=ToolAnnotations(
        title="Append to a knowledge unit",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
)
async def knowledge_add(
    id: Annotated[str, Field(description="Unit id to append to.")],
    content: Annotated[str, Field(description="Text to append at the end of the unit.")],
    if_version: Annotated[str, Field(description="Version token from a prior fetch.")],
) -> str:
    """Append content to the end of a unit, leaving what is there untouched.

    Prefer this over `knowledge_put` when recording something new: the store's contract
    is append-and-deprecate rather than rewrite, because history is context.
    """
    try:
        return _written("Appended to", store().add(id, content, if_version))
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        os.environ[ROOT_ENV] = args[0]
    if not os.environ.get(ROOT_ENV):
        print(f"error: set {ROOT_ENV} or pass the knowledge root as the first argument", file=sys.stderr)
        return 2
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
