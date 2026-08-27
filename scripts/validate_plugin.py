#!/usr/bin/env python3
"""Validate this repository's plugin source against the Agent Plugins template.

Complements the toolkit CLI rather than duplicating it. `agent-plugin validate`
checks portable-spec conformance; this checks the repository invariants the
spec has no opinion about:

  * version lockstep across VERSION, package.json and plugin.json
  * repository marketplace metadata points at the portable plugin source
    (Codex `.agents/plugins/marketplace.json` and Cursor `.cursor-plugin/marketplace.json`)
  * skill frontmatter restricted to portable keys, with name == directory
  * no skill content that the adapter payload allowlist would silently drop

Compiled payloads are deliberately out of scope: they are build output, not
committed state, so there is nothing here for them to drift from. `pnpm
payloads:build` is the gate that proves every adapter accepts this source.

Usage:  python3 scripts/validate_plugin.py [repo-root]
Exits 0 when clean, 1 with one `error: ...` line per problem on stderr.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLUGIN_DIR = "plugins/monolithic-code-review-toolkit"

# The portable SKILL.md contract. Host-only keys (disable-model-invocation,
# allowed-tools, license) are deliberately excluded: adapters do not carry them,
# so their presence would be a silent no-op.
PORTABLE_FRONTMATTER = frozenset({"name", "description"})

# Adapters emit only skills/<name>/SKILL.md from a skill directory. Anything
# else present in source would not ship. See ADR-0001.
ALLOWED_SKILL_FILES = frozenset({"SKILL.md"})

# Directories that cannot survive compilation to any vendor payload.
UNSHIPPABLE_DIRS = ("commands", "agents", "hooks")

NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
MARKETPLACE_PATH = ".agents/plugins/marketplace.json"
CURSOR_MARKETPLACE_PATH = ".cursor-plugin/marketplace.json"
EXPECTED_CURSOR_SOURCE = "plugins/monolithic-code-review-toolkit"

errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    return None


def parse_frontmatter(text: str, path: Path) -> dict[str, str] | None:
    """Parse the leading YAML frontmatter block.

    Deliberately not a YAML parser: the portable contract allows only two
    scalar keys, so a stricter reader catches drift a general parser would
    quietly accept.
    """
    if not text.startswith("---\n"):
        fail(f"{path}: must start with YAML frontmatter (---)")
        return None
    end = text.find("\n---\n", 3)
    if end == -1:
        fail(f"{path}: frontmatter is not closed")
        return None

    fields: dict[str, str] = {}
    key = None
    for line in text[4:end + 1].splitlines():
        if not line.strip():
            continue
        if line[0] in " \t":  # continuation of a folded/multiline value
            if key is None:
                fail(f"{path}: indented frontmatter line with no key")
                return None
            fields[key] += " " + line.strip()
            continue
        if ":" not in line:
            fail(f"{path}: unparseable frontmatter line: {line!r}")
            return None
        key, _, value = line.partition(":")
        key = key.strip()
        fields[key] = value.strip().strip("'\"")
    return fields


def check_versions(root: Path) -> str | None:
    version_file = root / "VERSION"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        fail("missing file: VERSION")
        return None

    if not SEMVER_RE.match(version):
        fail(f"VERSION is not semantic: {version!r}")

    package = read_json(root / "package.json")
    if package is not None and package.get("version") != version:
        fail(f"package.json version {package.get('version')!r} != VERSION {version!r}")

    manifest = read_json(root / PLUGIN_DIR / "plugin.json")
    if manifest is not None:
        if manifest.get("version") != version:
            fail(f"plugin.json version {manifest.get('version')!r} != VERSION {version!r}")
        name = manifest.get("name", "")
        if not NAME_RE.match(name):
            fail(f"plugin.json name is not a valid plugin identifier: {name!r}")
        if manifest.get("schemaVersion") != "1.0.0":
            fail("plugin.json must declare schemaVersion 1.0.0")
    return version


def check_skills(root: Path) -> int:
    skills_dir = root / PLUGIN_DIR / "skills"
    if not skills_dir.is_dir():
        fail(f"missing directory: {skills_dir}")
        return 0

    count = 0
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        count += 1
        rel = skill_dir.relative_to(root)

        for entry in sorted(skill_dir.iterdir()):
            if entry.name not in ALLOWED_SKILL_FILES:
                fail(
                    f"{rel}/{entry.name}: adapters ship only SKILL.md, so this "
                    f"would not reach any host (see ADR-0001)"
                )

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            fail(f"{rel}: missing SKILL.md")
            continue

        text = skill_file.read_text(encoding="utf-8")
        fields = parse_frontmatter(text, skill_file.relative_to(root))
        if fields is None:
            continue

        extra = set(fields) - PORTABLE_FRONTMATTER
        if extra:
            fail(f"{rel}/SKILL.md: non-portable frontmatter keys: {sorted(extra)}")
        missing = PORTABLE_FRONTMATTER - set(fields)
        if missing:
            fail(f"{rel}/SKILL.md: missing frontmatter keys: {sorted(missing)}")

        if fields.get("name") != skill_dir.name:
            fail(f"{rel}/SKILL.md: frontmatter name {fields.get('name')!r} != directory name")
        description = fields.get("description", "")
        if not 1 <= len(description) <= 1024:
            fail(f"{rel}/SKILL.md: description must be 1..1024 characters, got {len(description)}")

    if count == 0:
        fail("no skills found")
    return count


def check_marketplace(root: Path) -> None:
    marketplace = read_json(root / MARKETPLACE_PATH)
    if marketplace is None:
        return

    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        fail(f"{MARKETPLACE_PATH}: plugins must be an array")
        return

    entry = next(
        (item for item in plugins if item.get("name") == "monolithic-code-review-toolkit"),
        None,
    )
    if entry is None:
        fail(f"{MARKETPLACE_PATH}: missing monolithic-code-review-toolkit entry")
        return

    expected_source = {
        "source": "local",
        "path": "./plugins/monolithic-code-review-toolkit",
    }
    if entry.get("source") != expected_source:
        fail(f"{MARKETPLACE_PATH}: plugin source must be {expected_source!r}")

    policy = entry.get("policy")
    if not isinstance(policy, dict):
        fail(f"{MARKETPLACE_PATH}: plugin policy must be an object")
    else:
        if policy.get("installation") not in {
            "NOT_AVAILABLE", "AVAILABLE", "INSTALLED_BY_DEFAULT"
        }:
            fail(f"{MARKETPLACE_PATH}: invalid policy.installation")
        if policy.get("authentication") not in {"ON_INSTALL", "ON_USE"}:
            fail(f"{MARKETPLACE_PATH}: invalid policy.authentication")

    if not entry.get("category"):
        fail(f"{MARKETPLACE_PATH}: plugin category is required")


def check_cursor_marketplace(root: Path) -> None:
    marketplace = read_json(root / CURSOR_MARKETPLACE_PATH)
    if marketplace is None:
        return

    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        fail(f"{CURSOR_MARKETPLACE_PATH}: plugins must be an array")
        return

    entry = next(
        (item for item in plugins if item.get("name") == "monolithic-code-review-toolkit"),
        None,
    )
    if entry is None:
        fail(f"{CURSOR_MARKETPLACE_PATH}: missing monolithic-code-review-toolkit entry")
        return

    source = entry.get("source")
    if not isinstance(source, str) or not source.strip():
        fail(f"{CURSOR_MARKETPLACE_PATH}: plugin source must be a non-empty string path")
        return

    normalized = source.removeprefix("./").strip("/")
    if normalized.startswith("payloads/"):
        fail(
            f"{CURSOR_MARKETPLACE_PATH}: plugin source must not point at gitignored "
            f"build output ({source!r})"
        )

    if normalized != EXPECTED_CURSOR_SOURCE:
        fail(
            f"{CURSOR_MARKETPLACE_PATH}: plugin source must be {EXPECTED_CURSOR_SOURCE!r}, "
            f"got {source!r}"
        )

    plugin_root = (root / normalized).resolve()
    portable_manifest = plugin_root / "plugin.json"
    cursor_manifest = plugin_root / ".cursor-plugin" / "plugin.json"
    if not portable_manifest.is_file() and not cursor_manifest.is_file():
        fail(
            f"{CURSOR_MARKETPLACE_PATH}: plugin source {source!r} has no portable plugin.json "
            f"or .cursor-plugin/plugin.json"
        )


def check_unshippable(root: Path) -> None:
    for name in UNSHIPPABLE_DIRS:
        path = root / PLUGIN_DIR / name
        if path.exists():
            fail(
                f"{path.relative_to(root)}/: no adapter emits this directory; "
                f"it would not reach any host (see ADR-0001)"
            )


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

    version = check_versions(root)
    check_marketplace(root)
    check_cursor_marketplace(root)
    count = check_skills(root)
    check_unshippable(root)

    if errors:
        for message in errors:
            print(f"error: {message}", file=sys.stderr)
        return 1

    print(f"ok: monolithic-code-review-toolkit@{version} ({count} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
