#!/usr/bin/env python3.12
"""Install or uninstall the Monolithic Code Review Toolkit Codex adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

AGENT_FILENAMES = (
    "mcrt_review_orchestrator.toml",
    "mcrt_review_discovery.toml",
    "mcrt_review_validator.toml",
    "mcrt_review_adversarial.toml",
    "mcrt_review_poster.toml",
)
REQUIRED_DEPTH = 2
RECORD_NAME = "mcrt-codex-review-adapter-install.json"
MANUAL_SNIPPET = "[agents]\nmax_depth = 2"


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
        base = Path(args.codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    else:
        base = Path(args.project or Path.cwd()).expanduser().resolve() / ".codex"
    base = base.expanduser().resolve()
    return base / "agents", base / "config.toml", base / RECORD_NAME


def _section_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    header = f"[{section}]"
    starts = [index for index, line in enumerate(lines) if line.strip() == header]
    if len(starts) > 1:
        raise ValueError(f"config contains more than one {header} section")
    if not starts:
        return None
    start = starts[0]
    for index in range(start + 1, len(lines)):
        if lines[index].strip().startswith("[") and lines[index].strip().endswith("]"):
            return start, index
    return start, len(lines)


def plan_config_edit(contents: str) -> ConfigEdit:
    lines = contents.splitlines(keepends=True)
    bounds = _section_bounds(lines, "agents")
    if bounds is None:
        separator = "" if not contents or contents.endswith("\n\n") else ("\n" if contents.endswith("\n") else "\n\n")
        return ConfigEdit("append", contents, contents + f"{separator}[agents]\nmax_depth = {REQUIRED_DEPTH}\n")
    start, end = bounds
    matches = []
    pattern = re.compile(r"^(\s*max_depth\s*=\s*)(\d+)(\s*(?:#.*)?(?:\r?\n)?)$")
    for index in range(start + 1, end):
        match = pattern.match(lines[index])
        if match:
            matches.append((index, match))
        elif re.match(r"^\s*max_depth\s*=", lines[index]):
            raise ValueError(f"cannot safely parse max_depth; set it manually:\n{MANUAL_SNIPPET}")
    if len(matches) > 1:
        raise ValueError("config contains more than one agents.max_depth value")
    if not matches:
        lines.insert(end, f"max_depth = {REQUIRED_DEPTH}\n")
        return ConfigEdit("insert", contents, "".join(lines))
    index, match = matches[0]
    if int(match.group(2)) >= REQUIRED_DEPTH:
        return ConfigEdit("none", contents, contents)
    lines[index] = f"{match.group(1)}{REQUIRED_DEPTH}{match.group(3)}"
    return ConfigEdit("replace", contents, "".join(lines))


def _load_sources(adapter_root: Path) -> dict[str, bytes]:
    sources: dict[str, bytes] = {}
    placeholder = b"__MCRT_ADAPTER_ROOT__"
    root = str(adapter_root).encode("utf-8")
    for filename in AGENT_FILENAMES:
        path = adapter_root / "agents" / filename
        if not path.is_file():
            raise ValueError(f"missing adapter agent definition: {path}")
        contents = path.read_bytes()
        sources[filename] = contents.replace(placeholder, root)
    return sources


def _preflight(agents_dir: Path, config_path: Path, record_path: Path, sources: dict[str, bytes]) -> tuple[ConfigEdit, dict]:
    expected_hashes = {name: _sha256(data) for name, data in sources.items()}
    if record_path.exists():
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("agent_hashes") != expected_hashes:
            raise ValueError(f"an incompatible managed install record already exists: {record_path}")
        if not all((agents_dir / name).is_file() and _sha256((agents_dir / name).read_bytes()) == digest
                   for name, digest in expected_hashes.items()):
            raise ValueError(f"a managed custom agent changed after installation: {agents_dir}")
        before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        return plan_config_edit(before), record
    for filename, data in sources.items():
        destination = agents_dir / filename
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError(f"refusing to overwrite unmanaged custom agent: {destination}")
    before = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    edit = plan_config_edit(before)
    return edit, {
        "schema_version": 1,
        "agent_hashes": expected_hashes,
        "config_existed": config_path.exists(),
        "config_edit": asdict(edit),
    }


def install(args: argparse.Namespace) -> int:
    agents_dir, config_path, record_path = _paths(args)
    try:
        sources = _load_sources(_adapter_root())
        edit, record = _preflight(agents_dir, config_path, record_path, sources)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Blocked: {error}", file=sys.stderr)
        print(f"Manual configuration if needed:\n{MANUAL_SNIPPET}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps({"action": "install", "agents_dir": str(agents_dir), "config_action": edit.action}, indent=2))
        return 0
    agents_dir.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    for filename, data in sources.items():
        (agents_dir / filename).write_bytes(data)
    if edit.after != edit.before or not config_path.exists():
        config_path.write_text(edit.after, encoding="utf-8")
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Installed MCRT Codex review agents in {agents_dir}")
    print(f"Verified agents.max_depth >= {REQUIRED_DEPTH} in {config_path}")
    return 0


def uninstall(args: argparse.Namespace) -> int:
    agents_dir, config_path, record_path = _paths(args)
    if not record_path.is_file():
        print(f"No managed MCRT Codex review adapter install found at {record_path}")
        return 0
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        for filename, digest in record["agent_hashes"].items():
            path = agents_dir / filename
            if not path.is_file() or _sha256(path.read_bytes()) != digest:
                raise ValueError(f"managed agent changed after installation: {path}")
        edit = ConfigEdit(**record["config_edit"])
        contents = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        if edit.action != "none" and contents != edit.after:
            raise ValueError("config changed after installation; refusing to overwrite it during uninstall")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"Blocked: {error}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps({"action": "uninstall", "agents_dir": str(agents_dir)}, indent=2))
        return 0
    for filename in record["agent_hashes"]:
        (agents_dir / filename).unlink()
    if edit.action != "none":
        if not record["config_existed"] and edit.before == "":
            config_path.unlink(missing_ok=True)
        else:
            config_path.write_text(edit.before, encoding="utf-8")
    record_path.unlink()
    print(f"Uninstalled MCRT Codex review agents from {agents_dir}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("user", "project"), default="user")
    parser.add_argument("--project", help="Project root for --scope project (defaults to cwd)")
    parser.add_argument("--codex-home", help=argparse.SUPPRESS)
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
