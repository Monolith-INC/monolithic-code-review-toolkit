#!/usr/bin/env python3.12
"""Install or uninstall the Monolithic Code Review Toolkit knowledge MCP server.

Registers one stdio MCP server against a repository's knowledge store. Unlike the
review orchestrator adapters this writes no agents and no hooks — the whole adapter
is a server entry plus the root it points at.

    python3.12 install_knowledge_adapter.py --project /path/to/repo
    python3.12 install_knowledge_adapter.py --project /path/to/repo --uninstall

The store root defaults to `knowledge.root` in the repository's
`.monolithic-code-review/sources.json`, which is what `review-setup` records.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

SERVER_NAME = "mcrt-knowledge"
RECORD_NAME = "mcrt-knowledge-adapter-install.json"
SOURCES_RELATIVE = Path(".monolithic-code-review/sources.json")
DEFAULT_KNOWLEDGE_ROOT = ".monolithic-code-review/knowledge"
ROOT_ENV = "MCRT_KNOWLEDGE_ROOT"

MANUAL_SNIPPET = """{
  "mcpServers": {
    "mcrt-knowledge": {
      "command": "python3.12",
      "args": ["<adapter>/mcrt_knowledge_mcp.py"],
      "env": {"MCRT_KNOWLEDGE_ROOT": "<knowledge root>"}
    }
  }
}"""


@dataclass(frozen=True)
class ConfigEdit:
    action: str
    before: str
    after: str


def _adapter_root() -> Path:
    return Path(__file__).resolve().parent


def _project(args: argparse.Namespace) -> Path:
    return Path(args.project or Path.cwd()).expanduser().resolve()


def _config_path(args: argparse.Namespace) -> Path:
    return _project(args) / ".mcp.json"


def resolve_knowledge_root(project: Path, override: str | None) -> tuple[Path, str]:
    """Prefer what `review-setup` recorded; fall back to the documented default.

    Returns the root and where it came from, so the installer can say which it used
    rather than leaving the operator to guess.
    """
    if override:
        return Path(override).expanduser().resolve(), "--knowledge-root"

    sources = project / SOURCES_RELATIVE
    if sources.is_file():
        try:
            data = json.loads(sources.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"{sources} is not valid JSON: {error}") from error
        recorded = (data.get("knowledge") or {}).get("root")
        if recorded:
            root = Path(recorded)
            return (root if root.is_absolute() else project / root).resolve(), str(SOURCES_RELATIVE)
        if "knowledge" in data:
            raise ValueError(
                f"{sources} records knowledge.root as null: run review-setup and choose a store, "
                f"or pass --knowledge-root explicitly"
            )
    return (project / DEFAULT_KNOWLEDGE_ROOT).resolve(), "default"


def server_entry(adapter_root: Path, knowledge_root: Path) -> dict:
    return {
        "command": "python3.12",
        "args": [str(adapter_root / "mcrt_knowledge_mcp.py")],
        "env": {ROOT_ENV: str(knowledge_root)},
    }


def plan_config_edit(contents: str, adapter_root: Path, knowledge_root: Path) -> ConfigEdit:
    if not contents.strip():
        config: dict = {}
    else:
        try:
            config = json.loads(contents)
        except json.JSONDecodeError as error:
            raise ValueError(f".mcp.json is not valid JSON: {error}") from error
        if not isinstance(config, dict):
            raise ValueError(".mcp.json root must be an object")

    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(".mcp.json 'mcpServers' must be an object")

    entry = server_entry(adapter_root, knowledge_root)
    existing = servers.get(SERVER_NAME)
    if existing == entry:
        return ConfigEdit("none", contents, contents)
    if existing is not None and not _entry_is_ours(existing, adapter_root):
        raise ValueError(
            f"refusing to overwrite an unmanaged {SERVER_NAME!r} server entry; "
            f"remove it first or install with a different scope"
        )
    action = "replace" if existing is not None else "append"
    servers[SERVER_NAME] = entry
    return ConfigEdit(action, contents, json.dumps(config, indent=2) + "\n")


def plan_removal(contents: str, adapter_root: Path) -> ConfigEdit:
    if not contents.strip():
        return ConfigEdit("none", contents, contents)
    try:
        config = json.loads(contents)
    except json.JSONDecodeError as error:
        raise ValueError(f".mcp.json is not valid JSON: {error}") from error

    servers = config.get("mcpServers")
    if not isinstance(servers, dict) or SERVER_NAME not in servers:
        return ConfigEdit("none", contents, contents)
    if not _entry_is_ours(servers[SERVER_NAME], adapter_root):
        raise ValueError(f"the {SERVER_NAME!r} entry is not managed by this adapter; leaving it alone")

    del servers[SERVER_NAME]
    if not servers:
        del config["mcpServers"]
    return ConfigEdit("remove", contents, json.dumps(config, indent=2) + "\n")


def _entry_is_ours(entry: object, adapter_root: Path) -> bool:
    expected = str(adapter_root / "mcrt_knowledge_mcp.py")
    return isinstance(entry, dict) and expected in (entry.get("args") or [])


def install(args: argparse.Namespace) -> int:
    project = _project(args)
    adapter_root = _adapter_root()
    record_path = project / ".claude" / RECORD_NAME

    try:
        config_path = _config_path(args)
        knowledge_root, origin = resolve_knowledge_root(project, args.knowledge_root)
        before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        edit = plan_config_edit(before, adapter_root, knowledge_root)
    except (OSError, ValueError) as error:
        print(f"Blocked: {error}", file=sys.stderr)
        print(f"Manual configuration if needed:\n{MANUAL_SNIPPET}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(
            {
                "action": "install",
                "config": str(config_path),
                "config_action": edit.action,
                "knowledge_root": str(knowledge_root),
                "knowledge_root_source": origin,
                "server": SERVER_NAME,
            },
            indent=2,
        ))
        return 0

    if edit.action != "none":
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(edit.after, encoding="utf-8")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "adapter_root": str(adapter_root),
                "config_path": str(config_path),
                "knowledge_root": str(knowledge_root),
                "knowledge_root_source": origin,
                "config_action": edit.action,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Registered {SERVER_NAME} in {config_path} ({edit.action})")
    print(f"Knowledge root: {knowledge_root}  (from {origin})")
    if not knowledge_root.is_dir():
        print(
            "That root does not exist yet. Run "
            "`monolithic-code-review-toolkit:discover-project-knowledge` to build the store; "
            "the server serves an empty catalog until then."
        )
    print("Install the server's dependencies with: python3.12 -m pip install -e " + str(adapter_root))
    return 0


def uninstall(args: argparse.Namespace) -> int:
    project = _project(args)
    adapter_root = _adapter_root()
    record_path = project / ".claude" / RECORD_NAME

    try:
        config_path = _config_path(args)
        before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        edit = plan_removal(before, adapter_root)
    except (OSError, ValueError) as error:
        print(f"Blocked: {error}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps({"action": "uninstall", "config_action": edit.action}, indent=2))
        return 0

    if edit.action != "none":
        config_path.write_text(edit.after, encoding="utf-8")
    record_path.unlink(missing_ok=True)
    print(f"Removed {SERVER_NAME} from {config_path} ({edit.action})")
    print("The knowledge store itself was left untouched.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", help="Repository root. Defaults to the working directory.")
    parser.add_argument(
        "--knowledge-root",
        help="Override the store root. Defaults to knowledge.root in sources.json.",
    )
    parser.add_argument("--uninstall", action="store_true", help="Remove the server entry.")
    parser.add_argument("--dry-run", action="store_true", help="Report the planned change and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return uninstall(args) if args.uninstall else install(args)


if __name__ == "__main__":
    sys.exit(main())
