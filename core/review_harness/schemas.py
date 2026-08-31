"""JSON Schema evidence generated from the same product contract registry."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import (
    CAPABILITIES,
    CORE_CONTRACT_VERSION,
    EFFECTS,
    IDENTIFIER,
    READ_CAPABILITIES,
    SCM_CAPABILITIES,
    SOURCES_SCHEMA_VERSION,
    TRACKER_CAPABILITIES,
    WRITE_CAPABILITIES,
)

_IDENTIFIER_PATTERN = IDENTIFIER.pattern


def _capability_binding(capability: str) -> dict:
    """Emit the alternatives `validate_binding` actually accepts.

    Access and effect are fixed per capability and the path alternative exists
    only for reads, so tooling cannot bless a document the hooks refuse.
    """
    access = {"const": "write" if capability in WRITE_CAPABILITIES else "read"}
    effect = {"const": EFFECTS[capability]}
    alternatives = [
        {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "server", "tool", "access", "effect"],
            "properties": {
                "kind": {"const": "mcp_tool"},
                "server": {"type": "string", "pattern": _IDENTIFIER_PATTERN},
                "tool": {"type": "string", "pattern": _IDENTIFIER_PATTERN},
                "access": access, "effect": effect,
            },
        },
        {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "program", "args", "access", "effect"],
            "properties": {
                "kind": {"const": "command"},
                "program": {"type": "string", "pattern": _IDENTIFIER_PATTERN},
                "args": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "access": access, "effect": effect,
            },
        },
    ]
    if capability in READ_CAPABILITIES:
        alternatives.append({
            "type": "object", "additionalProperties": False,
            "required": ["kind", "path", "access", "effect"],
            "properties": {
                "kind": {"const": "path"},
                "path": {"type": "string", "pattern": "^(?!/)(?!.*(^|/)\\.\\.(/|$)).+$"},
                "access": access, "effect": effect,
            },
        })
    return {"oneOf": alternatives}


def _area(capabilities: frozenset[str], extra: dict | None = None) -> dict:
    owned = sorted(capabilities)
    properties: dict = {
        "capabilities": {"propertyNames": {"enum": owned}},
        "unsupported": {"items": {"enum": owned}},
    }
    properties.update(extra or {})
    return {"allOf": [{"$ref": "#/$defs/source"}, {"type": "object", "properties": properties}]}


def sources_schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://monolith.inc/mcrt/review-harness/sources-v2.schema.json",
        "title": "MCRT sources.json v2",
        "type": "object",
        "required": ["version", "scm", "tracker"],
        "properties": {
            "version": {"const": SOURCES_SCHEMA_VERSION},
            "scm": {"$ref": "#/$defs/scm"},
            "tracker": {"$ref": "#/$defs/tracker"},
        },
        "$defs": {
            "source": {
                "type": "object",
                "required": ["capabilities", "unsupported"],
                "properties": {
                    "capabilities": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {capability: _capability_binding(capability) for capability in sorted(CAPABILITIES)},
                    },
                    "unsupported": {"type": "array", "items": {"enum": sorted(CAPABILITIES)}},
                },
            },
            "scm": _area(SCM_CAPABILITIES, {"owner": {"type": "string"}, "repo": {"type": "string"}}),
            "tracker": _area(TRACKER_CAPABILITIES),
        },
        "x-mcrt-core-contract-version": CORE_CONTRACT_VERSION,
        "x-mcrt-effects": EFFECTS,
        "x-mcrt-write-capabilities": sorted(WRITE_CAPABILITIES),
    }


def write_schema_snapshots(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sources-v2.schema.json"
    path.write_text(json.dumps(sources_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return [path]
