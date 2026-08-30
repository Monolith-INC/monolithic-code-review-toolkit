"""JSON Schema evidence generated from the same product contract registry."""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import CAPABILITIES, CORE_CONTRACT_VERSION, EFFECTS, SOURCES_SCHEMA_VERSION, WRITE_CAPABILITIES


def sources_schema() -> dict:
    binding = {
        "oneOf": [
            {"type": "object", "additionalProperties": False, "required": ["kind", "server", "tool", "access", "effect"], "properties": {"kind": {"const": "mcp_tool"}, "server": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_.-]*$"}, "tool": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_.-]*$"}, "access": {"enum": ["read", "write"]}, "effect": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["kind", "program", "args", "access", "effect"], "properties": {"kind": {"const": "command"}, "program": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_.-]*$"}, "args": {"type": "array", "minItems": 1, "items": {"type": "string"}}, "access": {"enum": ["read", "write"]}, "effect": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["kind", "path", "access", "effect"], "properties": {"kind": {"const": "path"}, "path": {"type": "string"}, "access": {"const": "read"}, "effect": {"type": "string"}}},
        ]
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://monolith.inc/mcrt/review-harness/sources-v2.schema.json",
        "title": "MCRT sources.json v2",
        "type": "object",
        "required": ["version", "scm", "tracker"],
        "properties": {
            "version": {"const": SOURCES_SCHEMA_VERSION},
            "scm": {"$ref": "#/$defs/source"},
            "tracker": {"$ref": "#/$defs/source"},
        },
        "$defs": {"source": {"type": "object", "required": ["capabilities", "unsupported"], "properties": {"capabilities": {"type": "object", "propertyNames": {"enum": sorted(CAPABILITIES)}, "additionalProperties": binding}, "unsupported": {"type": "array", "items": {"enum": sorted(CAPABILITIES)}}}}},
        "x-mcrt-core-contract-version": CORE_CONTRACT_VERSION,
        "x-mcrt-effects": EFFECTS,
        "x-mcrt-write-capabilities": sorted(WRITE_CAPABILITIES),
    }


def write_schema_snapshots(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sources-v2.schema.json"
    path.write_text(json.dumps(sources_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return [path]
