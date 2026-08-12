"""Tests for scripts/validate_plugin.py.

Each test builds a minimal repository in a temp directory, mutates one thing,
and asserts the validator catches it. The real repository is covered by the
`accepts_this_repository` test at the end.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = "plugins/monolithic-code-review-toolkit"


def load_validator():
    """Import the script fresh so its module-level error list starts empty."""
    spec = importlib.util.spec_from_file_location(
        "validate_plugin", REPO_ROOT / "scripts" / "validate_plugin.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SKILL_TEMPLATE = """---
name: {name}
description: {description}
---

# {name}

Body.
"""


class ValidatorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mcrt-validate-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.build_repo()

    def build_repo(self, version: str = "0.1.0") -> None:
        (self.tmp / "VERSION").write_text(f"{version}\n", encoding="utf-8")
        (self.tmp / "package.json").write_text(
            json.dumps({"name": "monolithic-code-review-toolkit", "version": version}),
            encoding="utf-8",
        )
        plugin = self.tmp / PLUGIN_DIR
        (plugin / "skills").mkdir(parents=True)
        (plugin / "plugin.json").write_text(
            json.dumps({
                "schemaVersion": "1.0.0",
                "name": "monolithic-code-review-toolkit",
                "version": version,
            }),
            encoding="utf-8",
        )
        self.add_skill("review-task", "Reviews a task against its requirements.")

    def add_skill(self, name: str, description: str, frontmatter_name: str | None = None) -> Path:
        skill_dir = self.tmp / PLUGIN_DIR / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            SKILL_TEMPLATE.format(name=frontmatter_name or name, description=description),
            encoding="utf-8",
        )
        return skill_dir

    def run_validator(self) -> tuple[int, list[str]]:
        module = load_validator()
        argv = sys.argv
        sys.argv = ["validate_plugin.py", str(self.tmp)]
        try:
            code = module.main()
        finally:
            sys.argv = argv
        return code, module.errors

    def assert_clean(self) -> None:
        code, found = self.run_validator()
        self.assertEqual(code, 0, f"expected clean, got: {found}")

    def assert_error_matching(self, needle: str) -> None:
        code, found = self.run_validator()
        self.assertEqual(code, 1, "expected validation to fail")
        joined = "\n".join(found)
        self.assertIn(needle, joined, f"no error mentioning {needle!r} in:\n{joined}")


class TestBaseline(ValidatorTestCase):
    def test_accepts_a_well_formed_repository(self) -> None:
        self.assert_clean()


class TestVersionLockstep(ValidatorTestCase):
    def test_rejects_package_json_version_drift(self) -> None:
        (self.tmp / "package.json").write_text(
            json.dumps({"name": "x", "version": "0.2.0"}), encoding="utf-8"
        )
        self.assert_error_matching("package.json version")

    def test_rejects_plugin_manifest_version_drift(self) -> None:
        path = self.tmp / PLUGIN_DIR / "plugin.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["version"] = "9.9.9"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.assert_error_matching("plugin.json version")

    def test_rejects_non_semantic_version(self) -> None:
        (self.tmp / "VERSION").write_text("v1\n", encoding="utf-8")
        self.assert_error_matching("not semantic")


class TestSkillContract(ValidatorTestCase):
    def test_rejects_frontmatter_name_not_matching_directory(self) -> None:
        self.add_skill("review-feature", "Reviews a feature.", frontmatter_name="something-else")
        self.assert_error_matching("!= directory name")

    def test_rejects_non_portable_frontmatter_keys(self) -> None:
        skill = self.add_skill("review-setup", "Sets up review sources.")
        path = skill / "SKILL.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "description: Sets up review sources.",
                "description: Sets up review sources.\nallowed-tools: Read Write",
            ),
            encoding="utf-8",
        )
        self.assert_error_matching("non-portable frontmatter keys")

    def test_rejects_missing_frontmatter(self) -> None:
        skill = self.tmp / PLUGIN_DIR / "skills" / "no-frontmatter"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# Just a heading\n", encoding="utf-8")
        self.assert_error_matching("must start with YAML frontmatter")

    def test_rejects_empty_description(self) -> None:
        self.add_skill("review-empty", "")
        self.assert_error_matching("description must be 1..1024")

    def test_rejects_skill_missing_skill_md(self) -> None:
        (self.tmp / PLUGIN_DIR / "skills" / "hollow").mkdir(parents=True)
        self.assert_error_matching("missing SKILL.md")


class TestPayloadAllowlist(ValidatorTestCase):
    """ADR-0001: content adapters would silently drop must not exist in source."""

    def test_rejects_bundled_references_directory(self) -> None:
        references = self.tmp / PLUGIN_DIR / "skills" / "review-task" / "references"
        references.mkdir()
        (references / "notes.md").write_text("shared\n", encoding="utf-8")
        self.assert_error_matching("adapters ship only SKILL.md")

    def test_rejects_bundled_scripts_directory(self) -> None:
        scripts = self.tmp / PLUGIN_DIR / "skills" / "review-task" / "scripts"
        scripts.mkdir()
        (scripts / "helper.py").write_text("pass\n", encoding="utf-8")
        self.assert_error_matching("adapters ship only SKILL.md")

    def test_rejects_commands_directory(self) -> None:
        commands = self.tmp / PLUGIN_DIR / "commands"
        commands.mkdir(parents=True)
        (commands / "review-task.md").write_text("run it\n", encoding="utf-8")
        self.assert_error_matching("no adapter emits this directory")


class TestMissingPieces(ValidatorTestCase):
    def test_rejects_repository_with_no_skills(self) -> None:
        shutil.rmtree(self.tmp / PLUGIN_DIR / "skills")
        (self.tmp / PLUGIN_DIR / "skills").mkdir()
        self.assert_error_matching("no skills found")


class TestRealRepository(unittest.TestCase):
    def test_accepts_this_repository(self) -> None:
        module = load_validator()
        argv = sys.argv
        sys.argv = ["validate_plugin.py", str(REPO_ROOT)]
        try:
            code = module.main()
        finally:
            sys.argv = argv
        self.assertEqual(code, 0, f"this repository does not validate: {module.errors}")


if __name__ == "__main__":
    unittest.main()
