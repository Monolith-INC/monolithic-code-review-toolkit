#!/usr/bin/env python3.12
"""Install or uninstall the Monolithic Code Review Toolkit Claude adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

AGENT_FILENAMES = (
    "mcrt-review-discovery.md",
    "mcrt-review-validator.md",
    "mcrt-review-adversarial.md",
    "mcrt-review-poster.md",
)
SKILL_NAME = "mcrt-review"
RECORD_NAME = "mcrt-claude-review-adapter-install.json"
# The guarded surface is data-driven from sources.json, so this only has to be
# wide enough to reach the hook: it filters exactly, against the registered write
# bindings. It must route every comment/thread write tool name a binding can name,
# including mcp__<server>__post_comment.
DEFAULT_HOOK_MATCHER = (
    "Bash|.*comment.*|.*pull_request.*|.*review_thread.*|.*thread_write.*|"
    ".*create_review.*|.*post_review.*|.*submit_review.*|.*add_review.*|.*write_review.*"
)
ADAPTER_ROOT_PLACEHOLDER = "__MCRT_ADAPTER_ROOT__"
SCM_TOOLS_PLACEHOLDER = "__MCRT_SCM_TOOLS__"
SCM_READ_TOOLS_PLACEHOLDER = "__MCRT_SCM_READ_TOOLS__"
# The guard is one hook on three events: PreToolUse authorizes the post, and the
# post events resolve that authorization. Registering only PreToolUse would
# leave every authorization pending forever.
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")
MANUAL_SNIPPET = """{
  "hooks": {
    "PreToolUse": [
      {"matcher": "<matcher>", "hooks": [{"type": "command", "command": "python3.12 <adapter>/mcrt_poster_guard_hook.py", "timeout": 5}]}
    ],
    "PostToolUse": [
      {"matcher": "<matcher>", "hooks": [{"type": "command", "command": "python3.12 <adapter>/mcrt_poster_guard_hook.py", "timeout": 5}]}
    ],
    "PostToolUseFailure": [
      {"matcher": "<matcher>", "hooks": [{"type": "command", "command": "python3.12 <adapter>/mcrt_poster_guard_hook.py", "timeout": 5}]}
    ]
  }
}"""


@dataclass(frozen=True)
class ConfigEdit:
    action: str
    before: str
    after: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _adapter_root() -> Path:
    return Path(__file__).resolve().parent


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    if args.scope == "user":
        base = Path(args.claude_home or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    else:
        base = Path(args.project or Path.cwd()).expanduser().resolve() / ".claude"
    base = base.expanduser().resolve()
    return base, base / "settings.json", base / RECORD_NAME


def hook_command(adapter_root: Path) -> str:
    return f"python3.12 {adapter_root / 'mcrt_poster_guard_hook.py'}"


def _hook_entry(adapter_root: Path, matcher: str) -> dict:
    return {
        "matcher": matcher,
        "hooks": [{"type": "command", "command": hook_command(adapter_root), "timeout": 5}],
    }


def _entry_is_ours(entry: object, command: str) -> bool:
    return (
        isinstance(entry, dict)
        and any(
            isinstance(hook, dict) and hook.get("command") == command
            for hook in entry.get("hooks", []) if isinstance(entry.get("hooks"), list)
        )
    )


def plan_config_edit(contents: str, adapter_root: Path, matcher: str) -> ConfigEdit:
    command = hook_command(adapter_root)
    if not contents.strip():
        settings: dict = {}
    else:
        try:
            settings = json.loads(contents)
        except json.JSONDecodeError as error:
            raise ValueError(f"settings.json is not valid JSON: {error}") from error
        if not isinstance(settings, dict):
            raise ValueError("settings.json root must be an object")
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings.json 'hooks' must be an object")
    entry = _hook_entry(adapter_root, matcher)
    actions: set[str] = set()
    for event in HOOK_EVENTS:
        registered = hooks.setdefault(event, [])
        if not isinstance(registered, list):
            raise ValueError(f"settings.json 'hooks.{event}' must be a list")
        existing = [index for index, item in enumerate(registered) if _entry_is_ours(item, command)]
        if len(existing) > 1:
            raise ValueError(f"settings.json already contains more than one managed MCRT hook entry in {event}")
        if not existing:
            registered.append(entry)
            actions.add("append")
        elif registered[existing[0]] != entry:
            registered[existing[0]] = entry
            actions.add("replace")
    if not actions:
        return ConfigEdit("none", contents, contents)
    action = "append" if "append" in actions else "replace"
    after = json.dumps(settings, indent=2) + "\n"
    return ConfigEdit(action, contents, after)


def _load_sources(
    adapter_root: Path, scm_tools: list[str], scm_read_tools: list[str] | None = None,
) -> dict[str, bytes]:
    sources: dict[str, bytes] = {}
    write_suffix = "".join(f", {tool}" for tool in scm_tools).encode("utf-8")
    read_suffix = "".join(f", {tool}" for tool in (scm_read_tools or [])).encode("utf-8")
    for filename in AGENT_FILENAMES:
        path = adapter_root / "agents" / filename
        if not path.is_file():
            raise ValueError(f"missing adapter agent definition: {path}")
        sources[f"agents/{filename}"] = (
            path.read_bytes()
            .replace(SCM_TOOLS_PLACEHOLDER.encode("utf-8"), write_suffix)
            .replace(SCM_READ_TOOLS_PLACEHOLDER.encode("utf-8"), read_suffix)
        )
    skill = adapter_root / "skills" / SKILL_NAME / "SKILL.md"
    if not skill.is_file():
        raise ValueError(f"missing adapter skill: {skill}")
    sources[f"skills/{SKILL_NAME}/SKILL.md"] = skill.read_bytes().replace(
        ADAPTER_ROOT_PLACEHOLDER.encode("utf-8"), str(adapter_root).encode("utf-8"),
    )
    return sources


def _preflight(
    base: Path, config_path: Path, record_path: Path, sources: dict[str, bytes],
    adapter_root: Path, matcher: str,
) -> tuple[ConfigEdit, dict]:
    expected_hashes = {name: _sha256(data) for name, data in sources.items()}
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("file_hashes") != expected_hashes:
            raise ValueError(f"an incompatible managed install record already exists: {record_path}")
        for name, digest in expected_hashes.items():
            path = base / name
            if not path.is_file() or _sha256(path.read_bytes()) != digest:
                raise ValueError(f"a managed adapter file changed after installation: {path}")
        return plan_config_edit(before, adapter_root, matcher), record
    for name, data in sources.items():
        destination = base / name
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError(f"refusing to overwrite unmanaged file: {destination}")
    edit = plan_config_edit(before, adapter_root, matcher)
    return edit, {
        "schema_version": 1,
        "adapter_root": str(adapter_root),
        "file_hashes": expected_hashes,
        "config_existed": config_path.exists(),
        "config_edit": asdict(edit),
    }


def install(args: argparse.Namespace) -> int:
    base, config_path, record_path = _paths(args)
    adapter_root = _adapter_root()
    try:
        sources = _load_sources(adapter_root, args.scm_tool, args.scm_read_tool)
        edit, record = _preflight(base, config_path, record_path, sources, adapter_root, args.matcher)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Blocked: {error}", file=sys.stderr)
        print(f"Manual configuration if needed:\n{MANUAL_SNIPPET}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps({
            "action": "install", "base": str(base), "files": sorted(sources),
            "config_action": edit.action, "scm_tools": args.scm_tool,
            "scm_read_tools": args.scm_read_tool,
        }, indent=2))
        return 0
    for name, data in sources.items():
        destination = base / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    if edit.action != "none":
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(edit.after, encoding="utf-8")
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Installed MCRT Claude review adapter in {base}")
    print(f"Registered poster guard for {', '.join(HOOK_EVENTS)} in {config_path} ({edit.action})")
    if not args.scm_tool:
        print("No --scm-tool given: the poster ships without provider MCP tools, which is correct "
              "for CLI-based providers. Add them for an MCP-based provider and reinstall.")
    if not args.scm_read_tool:
        print("No --scm-read-tool given: discovery and validator can verify only shell-reachable "
              "capabilities, and will report MCP-based ones as unverified.")
    return 0


def uninstall(args: argparse.Namespace) -> int:
    base, config_path, record_path = _paths(args)
    if not record_path.is_file():
        print(f"No managed MCRT Claude review adapter install found at {record_path}")
        return 0
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        for name, digest in record["file_hashes"].items():
            path = base / name
            if not path.is_file() or _sha256(path.read_bytes()) != digest:
                raise ValueError(f"managed file changed after installation: {path}")
        edit = ConfigEdit(**record["config_edit"])
        contents = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        if edit.action != "none" and contents != edit.after:
            raise ValueError("settings.json changed after installation; refusing to overwrite it")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"Blocked: {error}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps({"action": "uninstall", "base": str(base)}, indent=2))
        return 0
    for name in record["file_hashes"]:
        (base / name).unlink()
    skill_dir = base / "skills" / SKILL_NAME
    if skill_dir.is_dir() and not any(skill_dir.iterdir()):
        skill_dir.rmdir()
    if edit.action != "none":
        if not record["config_existed"] and edit.before == "":
            config_path.unlink(missing_ok=True)
        else:
            config_path.write_text(edit.before, encoding="utf-8")
    record_path.unlink()
    print(f"Uninstalled MCRT Claude review adapter from {base}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("user", "project"), default="user")
    parser.add_argument("--project", help="Project root for --scope project (defaults to cwd)")
    parser.add_argument("--claude-home", help=argparse.SUPPRESS)
    parser.add_argument(
        "--scm-tool", action="append", default=[], metavar="TOOL",
        help="MCP tool the poster may call to write pull-request comments. Repeatable. "
             "Omit for CLI-based providers, which post through Bash.",
    )
    parser.add_argument(
        "--scm-read-tool", action="append", default=[], metavar="TOOL",
        help="Read-only MCP tool the discovery and validator workers may call to inspect pull "
             "requests and work items. Repeatable. Without it those workers can verify only "
             "capabilities reachable through the shell, and will report MCP-based ones as "
             "unverified rather than guessing.",
    )
    parser.add_argument(
        "--matcher", default=DEFAULT_HOOK_MATCHER,
        help="PreToolUse matcher for the poster guard. The hook self-filters, so a broader "
             "matcher is safe but costs a process spawn per matched call.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.scope == "user" and args.project:
        print("--project is only valid with --scope project", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(uninstall(args) if args.uninstall else install(args))


if __name__ == "__main__":
    main()
