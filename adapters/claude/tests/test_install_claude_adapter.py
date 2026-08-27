from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import sys
import unittest
from argparse import Namespace
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("install_claude_adapter", ADAPTER / "install_claude_adapter.py")
assert _spec is not None and _spec.loader is not None
INSTALL = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = INSTALL
_spec.loader.exec_module(INSTALL)


def args(project: Path, **overrides) -> Namespace:
    fields = {
        "scope": "project", "project": str(project), "claude_home": None, "scm_tool": [],
        "matcher": INSTALL.DEFAULT_HOOK_MATCHER, "dry_run": False, "uninstall": False,
        "scm_read_tool": [],
    }
    fields.update(overrides)
    return Namespace(**fields)


def tools_line(body: bytes | str) -> str:
    """The agent's `tools:` frontmatter line, without its line ending.

    Extracting the line lets each test assert the whole thing with assertEqual,
    which catches an unexpected extra tool that a substring check would pass.
    """
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    for line in text.splitlines():
        if line.startswith("tools:"):
            return line
    raise AssertionError("no tools: line found")


def install(*call_args, **kwargs) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return INSTALL.install(args(*call_args, **kwargs))


def uninstall(*call_args, **kwargs) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return INSTALL.uninstall(args(*call_args, uninstall=True, **kwargs))


class ConfigEditTest(unittest.TestCase):
    def test_creates_hooks_block_in_empty_settings(self):
        edit = INSTALL.plan_config_edit("", ADAPTER, "Bash")
        self.assertEqual(edit.action, "append")
        settings = json.loads(edit.after)
        entry = settings["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "Bash")
        self.assertIn("mcrt_poster_guard_hook.py", entry["hooks"][0]["command"])

    def test_preserves_unrelated_settings_and_hooks(self):
        before = json.dumps({
            "model": "opus",
            "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "other.py"}]}]},
        })
        after = json.loads(INSTALL.plan_config_edit(before, ADAPTER, "Bash").after)
        self.assertEqual(after["model"], "opus")
        self.assertEqual(len(after["hooks"]["PreToolUse"]), 2)
        self.assertEqual(after["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "other.py")

    def test_reinstall_is_idempotent(self):
        once = INSTALL.plan_config_edit("", ADAPTER, "Bash").after
        twice = INSTALL.plan_config_edit(once, ADAPTER, "Bash")
        self.assertEqual(twice.action, "none")

    def test_matcher_change_replaces_rather_than_duplicates(self):
        once = INSTALL.plan_config_edit("", ADAPTER, "Bash").after
        edit = INSTALL.plan_config_edit(once, ADAPTER, "Bash|.*pr.*")
        self.assertEqual(edit.action, "replace")
        self.assertEqual(len(json.loads(edit.after)["hooks"]["PreToolUse"]), 1)

    def test_rejects_invalid_settings_json(self):
        with self.assertRaises(ValueError):
            INSTALL.plan_config_edit("{not json", ADAPTER, "Bash")

    def test_rejects_wrong_shaped_hooks(self):
        with self.assertRaises(ValueError):
            INSTALL.plan_config_edit(json.dumps({"hooks": {"PreToolUse": "nope"}}), ADAPTER, "Bash")


class SourceSubstitutionTest(unittest.TestCase):
    def test_skill_gets_the_absolute_adapter_root(self):
        sources = INSTALL._load_sources(ADAPTER, [])
        skill = sources["skills/mcrt-review/SKILL.md"].decode("utf-8")
        self.assertNotIn(INSTALL.ADAPTER_ROOT_PLACEHOLDER, skill)
        self.assertIn(str(ADAPTER), skill)

    def test_poster_tools_default_to_no_mcp_tools(self):
        poster = INSTALL._load_sources(ADAPTER, [])["agents/mcrt-review-poster.md"].decode("utf-8")
        self.assertNotIn(INSTALL.SCM_TOOLS_PLACEHOLDER, poster)
        self.assertEqual(tools_line(poster), "tools: Read, Grep, Glob, Bash")

    def test_scm_tools_are_appended_to_the_poster(self):
        poster = INSTALL._load_sources(ADAPTER, ["mcp__x__write", "mcp__y__write"])[
            "agents/mcrt-review-poster.md"].decode("utf-8")
        self.assertEqual(tools_line(poster),
                         "tools: Read, Grep, Glob, Bash, mcp__x__write, mcp__y__write")

    def test_read_tools_default_to_none_on_discovery_and_validator(self):
        sources = INSTALL._load_sources(ADAPTER, [], [])
        for name in ("mcrt-review-discovery.md", "mcrt-review-validator.md"):
            body = sources[f"agents/{name}"].decode("utf-8")
            self.assertNotIn(INSTALL.SCM_READ_TOOLS_PLACEHOLDER, body, name)
        self.assertEqual(tools_line(sources["agents/mcrt-review-discovery.md"]),
                         "tools: Read, Grep, Glob, Bash, Write")

    def test_read_tools_reach_discovery_and_validator_only(self):
        sources = INSTALL._load_sources(ADAPTER, ["mcp__x__write"], ["mcp__x__read"])
        discovery = sources["agents/mcrt-review-discovery.md"].decode("utf-8")
        validator = sources["agents/mcrt-review-validator.md"].decode("utf-8")
        poster = sources["agents/mcrt-review-poster.md"].decode("utf-8")
        adversarial = sources["agents/mcrt-review-adversarial.md"].decode("utf-8")
        self.assertTrue(tools_line(discovery).endswith("Write, mcp__x__read"), tools_line(discovery))
        self.assertTrue(tools_line(validator).endswith("Skill, mcp__x__read"), tools_line(validator))
        self.assertNotIn("mcp__x__read", poster)
        self.assertNotIn("mcp__x__", adversarial)

    def test_write_tools_never_reach_the_read_only_workers(self):
        sources = INSTALL._load_sources(ADAPTER, ["mcp__x__write"], ["mcp__x__read"])
        for name in ("mcrt-review-discovery.md", "mcrt-review-validator.md",
                     "mcrt-review-adversarial.md"):
            self.assertNotIn("mcp__x__write", sources[f"agents/{name}"].decode("utf-8"), name)

    def test_every_agent_and_the_skill_are_shipped(self):
        sources = INSTALL._load_sources(ADAPTER, [], [])
        self.assertEqual(len(sources), len(INSTALL.AGENT_FILENAMES) + 1)


class InstallRoundTripTest(unittest.TestCase):
    def test_install_then_uninstall_restores_the_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.assertEqual(install(project), 0)
            base = project / ".claude"
            for name in INSTALL.AGENT_FILENAMES:
                self.assertTrue((base / "agents" / name).is_file(), name)
            self.assertTrue((base / "skills" / "mcrt-review" / "SKILL.md").is_file())
            self.assertTrue((base / "settings.json").is_file())

            self.assertEqual(uninstall(project), 0)
            self.assertFalse((base / "agents" / INSTALL.AGENT_FILENAMES[0]).exists())
            self.assertFalse((base / "settings.json").exists())
            self.assertFalse((base / INSTALL.RECORD_NAME).exists())

    def test_uninstall_preserves_a_pre_existing_settings_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            base = project / ".claude"
            base.mkdir()
            original = json.dumps({"model": "opus"}, indent=2) + "\n"
            (base / "settings.json").write_text(original, encoding="utf-8")

            install(project)
            self.assertIn("PreToolUse", (base / "settings.json").read_text(encoding="utf-8"))
            uninstall(project)
            self.assertEqual((base / "settings.json").read_text(encoding="utf-8"), original)

    def test_reinstall_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.assertEqual(install(project), 0)
            self.assertEqual(install(project), 0)

    def test_refuses_to_overwrite_an_unmanaged_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            agents = project / ".claude" / "agents"
            agents.mkdir(parents=True)
            (agents / INSTALL.AGENT_FILENAMES[0]).write_text("mine, not yours", encoding="utf-8")
            self.assertEqual(install(project), 2)

    def test_refuses_uninstall_when_a_managed_file_was_edited(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            install(project)
            target = project / ".claude" / "agents" / INSTALL.AGENT_FILENAMES[0]
            target.write_text(target.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
            self.assertEqual(uninstall(project), 2)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.assertEqual(install(project, dry_run=True), 0)
            self.assertFalse((project / ".claude" / "agents").exists())

    def test_uninstall_without_an_install_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(uninstall(Path(tmp)), 0)


if __name__ == "__main__":
    unittest.main()
