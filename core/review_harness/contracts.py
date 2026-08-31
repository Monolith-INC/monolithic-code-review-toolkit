"""The product-owned review-harness contract registry.

Adapters may translate host payloads and render configuration, but they never
define review roles, capability names, or binding semantics.  This module has
no host dependency and deliberately uses only the Python standard library so
that the gate remains available inside a synchronous hook.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from copy import deepcopy
from typing import Any

CORE_CONTRACT_VERSION = 1
SOURCES_SCHEMA_VERSION = 2
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
PLACEHOLDER = re.compile(r"^\{(workspace|work_item_id|pull_request_id|owner|repo|body_file|body|path|line)\}$")

REVIEW_SKILLS = {
    "task": "review-task",
    "story-preflight": "review-story-preflight",
    "story-postflight": "review-story-postflight",
    "feature": "review-feature",
    "pr-preparation": "prepare-pr-for-review",
    "pr-comment-triage": "triage-pr-comments",
}
ROLE_IDS = frozenset({"orchestrator", "discovery", "validator", "adversarial", "poster"})
READ_CAPABILITIES = frozenset({
    "get_pull_request", "get_pull_request_diff", "list_review_threads",
    "list_conversation_comments", "fetch_work_item", "fetch_parent",
    "list_linked_artifacts",
})
WRITE_CAPABILITIES = frozenset({"post_inline_comment", "post_summary_comment", "reply_to_review_thread"})
CAPABILITIES = READ_CAPABILITIES | WRITE_CAPABILITIES
EFFECTS = {
    "get_pull_request": "scm.pull_request.read",
    "get_pull_request_diff": "scm.pull_request.read",
    "list_review_threads": "scm.review_thread.read",
    "list_conversation_comments": "scm.comment.read",
    "post_inline_comment": "scm.comment.create",
    "post_summary_comment": "scm.comment.create",
    "reply_to_review_thread": "scm.review_thread.reply",
    "fetch_work_item": "tracker.work_item.read",
    "fetch_parent": "tracker.work_item.read",
    "list_linked_artifacts": "tracker.artifact.read",
}
SCM_CAPABILITIES = frozenset(cap for cap, effect in EFFECTS.items() if effect.startswith("scm."))
TRACKER_CAPABILITIES = frozenset(cap for cap, effect in EFFECTS.items() if effect.startswith("tracker."))
AREA_CAPABILITIES = {"scm": SCM_CAPABILITIES, "tracker": TRACKER_CAPABILITIES}


class ContractError(ValueError):
    """A payload violates an explicit product contract."""


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContractError(f"{field} must be an identifier")
    return value


def _relative_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in value.split("/"):
        raise ContractError(f"{field} must be a bounded repository-relative path")
    return value


def _args(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ContractError("command.args must be a non-empty string array")
    for item in value:
        for part in re.findall(r"\{[^}]+\}", item):
            if not PLACEHOLDER.fullmatch(part):
                raise ContractError(f"command.args has unsupported placeholder {part}")
    return list(value)


def validate_binding(capability: str, value: Any) -> dict[str, Any]:
    """Validate and normalize one logical capability binding."""
    if capability not in CAPABILITIES:
        raise ContractError(f"unknown capability: {capability}")
    if not isinstance(value, dict):
        raise ContractError(f"{capability} binding must be an object")
    kind = value.get("kind")
    access = "write" if capability in WRITE_CAPABILITIES else "read"
    effect = EFFECTS[capability]
    if value.get("access") != access:
        raise ContractError(f"{capability}.access must be {access!r}")
    if value.get("effect") != effect:
        raise ContractError(f"{capability}.effect must be {effect!r}")
    if kind == "mcp_tool":
        if set(value) != {"kind", "server", "tool", "access", "effect"}:
            raise ContractError(f"{capability} mcp_tool has unknown or missing fields")
        return {
            "kind": kind, "server": _identifier(value["server"], f"{capability}.server"),
            "tool": _identifier(value["tool"], f"{capability}.tool"),
            "access": access, "effect": effect,
        }
    if kind == "command":
        if set(value) != {"kind", "program", "args", "access", "effect"}:
            raise ContractError(f"{capability} command has unknown or missing fields")
        return {
            "kind": kind, "program": _identifier(value["program"], f"{capability}.program"),
            "args": _args(value["args"]), "access": access, "effect": effect,
        }
    if kind == "path":
        if capability not in READ_CAPABILITIES or set(value) != {"kind", "path", "access", "effect"}:
            raise ContractError(f"{capability} path binding is invalid")
        return {"kind": kind, "path": _relative_path(value["path"], f"{capability}.path"), "access": access, "effect": effect}
    raise ContractError(f"{capability}.kind must be mcp_tool, command, or path")


def validate_sources(value: Any) -> dict[str, Any]:
    """Validate the v2, repository-local binding document used by every host."""
    if not isinstance(value, dict) or value.get("version") != SOURCES_SCHEMA_VERSION:
        raise ContractError(f"sources.json must declare version {SOURCES_SCHEMA_VERSION}")
    scm = value.get("scm")
    tracker = value.get("tracker")
    if not isinstance(scm, dict) or not isinstance(tracker, dict):
        raise ContractError("sources.json requires scm and tracker objects")
    result = deepcopy(value)
    for area in ("scm", "tracker"):
        section = result[area]
        capabilities = section.get("capabilities")
        unsupported = section.get("unsupported", [])
        if not isinstance(capabilities, dict) or not isinstance(unsupported, list) or not all(isinstance(x, str) for x in unsupported):
            raise ContractError(f"{area} capabilities and unsupported must be structured")
        for capability, binding in list(capabilities.items()):
            if capability not in AREA_CAPABILITIES[area]:
                raise ContractError(f"{capability} does not belong in {area}")
            capabilities[capability] = validate_binding(capability, binding)
    return result


def binding_digest(sources: dict[str, Any]) -> str:
    """Hash normalized bindings; a later config change invalidates approval."""
    normalized = validate_sources(sources)
    bindings = {area: normalized[area].get("capabilities", {}) for area in ("scm", "tracker")}
    encoded = json.dumps(bindings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def migrate_sources_v1(value: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Conservatively migrate old string mappings without changing source data.

    Only exact MCP identifiers and shell words that `shlex` can parse are
    converted.  A caller must report diagnostics and leave the v1 file in
    place when this function returns ``None``.
    """
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ContractError("only sources.json version 1 can be migrated")
    candidate = deepcopy(value)
    candidate["version"] = SOURCES_SCHEMA_VERSION
    diagnostics: list[str] = []
    for area in ("scm", "tracker"):
        section = candidate.get(area)
        if not isinstance(section, dict):
            diagnostics.append(f"{area}: missing object")
            continue
        capabilities = section.get("capabilities", {})
        if not isinstance(capabilities, dict):
            diagnostics.append(f"{area}.capabilities: missing object")
            continue
        for capability, raw in list(capabilities.items()):
            if capability not in CAPABILITIES or not isinstance(raw, str):
                diagnostics.append(f"{area}.{capability}: cannot migrate non-string mapping")
                continue
            access = "write" if capability in WRITE_CAPABILITIES else "read"
            effect = EFFECTS[capability]
            if raw.startswith("mcp__"):
                parts = raw.split("__")
                if len(parts) == 3 and all(IDENTIFIER.fullmatch(part) for part in parts[1:]):
                    capabilities[capability] = {"kind": "mcp_tool", "server": parts[1], "tool": parts[2], "access": access, "effect": effect}
                    continue
            try:
                words = shlex.split(raw)
            except ValueError:
                words = []
            if words and all(";" not in word and "|" not in word and "$(`" not in word for word in words):
                program, args = words[0], words[1:]
                if IDENTIFIER.fullmatch(program):
                    capabilities[capability] = {"kind": "command", "program": program, "args": args or ["--help"], "access": access, "effect": effect}
                    continue
            diagnostics.append(f"{area}.{capability}: ambiguous command mapping; rerun review-setup")
    if diagnostics:
        return None, diagnostics
    try:
        return validate_sources(candidate), []
    except ContractError as error:
        return None, [str(error)]
