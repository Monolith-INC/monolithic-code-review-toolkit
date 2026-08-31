from __future__ import annotations

import importlib.util
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ADAPTER = Path(__file__).resolve().parents[1]
INSTALLER_PATH = ADAPTER / "install_codex_adapter.py"
SPEC = importlib.util.spec_from_file_location("mcrt_install", INSTALLER_PATH)
assert SPEC is not None and SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INSTALLER
SPEC.loader.exec_module(INSTALLER)


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "codex-home"

    def tearDown(self):
        self.temp.cleanup()

    def run_installer(self, *extra):
        return subprocess.run([sys.executable, str(INSTALLER_PATH), "--codex-home", str(self.home), *extra], capture_output=True, text=True)

    def test_dry_run_writes_nothing(self):
        result = self.run_installer("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.home.exists())

    def test_install_is_idempotent_and_uninstall_restores_config(self):
        self.home.mkdir()
        config = self.home / "config.toml"
        original = 'model = "example"\n'
        config.write_text(original, encoding="utf-8")
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertIn("max_depth = 2", config.read_text(encoding="utf-8"))
        for filename in INSTALLER.AGENT_FILENAMES:
            self.assertTrue((self.home / "agents" / filename).is_file())
        self.assertEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertEqual(config.read_text(encoding="utf-8"), original)

    def test_conflicting_agent_is_not_overwritten(self):
        conflict = self.home / "agents" / INSTALLER.AGENT_FILENAMES[0]
        conflict.parent.mkdir(parents=True)
        conflict.write_text("unmanaged", encoding="utf-8")
        result = self.run_installer()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(conflict.read_text(encoding="utf-8"), "unmanaged")

    def test_project_scope_uses_project_codex_directory(self):
        project = Path(self.temp.name) / "project"
        project.mkdir()
        result = subprocess.run([sys.executable, str(INSTALLER_PATH), "--scope", "project", "--project", str(project)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((project / ".codex" / "agents" / INSTALLER.AGENT_FILENAMES[0]).is_file())

    def test_low_depth_is_replaced_surgically(self):
        edit = INSTALLER.plan_config_edit("[agents]\nmax_depth = 1 # old\n\n[features]\nhooks = true\n")
        self.assertEqual(edit.action, "replace")
        self.assertIn("max_depth = 2 # old", edit.after)

    def test_install_record_tracks_rendered_agent_hashes(self):
        self.assertEqual(self.run_installer().returncode, 0)
        record = json.loads((self.home / INSTALLER.RECORD_NAME).read_text(encoding="utf-8"))
        self.assertEqual(set(record["agent_hashes"]), set(INSTALLER.AGENT_FILENAMES))



class LifecycleInstructionTest(unittest.TestCase):
    """The shipped Codex instructions must agree with the enforced state machine."""

    def poster(self) -> str:
        return (ADAPTER / "agents" / "mcrt_review_poster.toml").read_text(encoding="utf-8")

    def test_the_poster_requires_an_approved_checkpoint(self):
        body = self.poster()
        self.assertIn("approved checkpoint", body)
        self.assertNotIn("completed approval", body)

    def test_the_poster_is_told_to_mark_every_comment(self):
        """Provenance is the marker now, so an unmarked post cannot be authorized."""
        self.assertIn("[mcrt:", self.poster())


class HookRegistrationTest(unittest.TestCase):
    def edit(self, root: str = "/tmp/codex"):
        return INSTALLER.plan_config_edit("", Path(root))

    def test_the_matcher_is_bounded(self):
        after = self.edit().after
        self.assertNotIn('matcher = ".*"', after)

    def test_the_matcher_routes_writes_but_not_ordinary_tools(self):
        matcher = INSTALLER.HOOK_MATCHER
        for tool in ("Bash", "mcp__github__post_comment", "mcp__github__pull_request_thread_write"):
            with self.subTest(tool=tool):
                self.assertRegex(tool, matcher)
        for tool in ("Read", "Edit", "Grep", "Glob", "WebFetch"):
            with self.subTest(tool=tool):
                self.assertNotRegex(tool, matcher)

    def test_pre_and_post_hooks_share_one_matcher(self):
        after = self.edit().after
        self.assertEqual(after.count(f'matcher = "{INSTALLER.HOOK_MATCHER}"'), 2)

    def test_an_awkward_adapter_path_stays_parseable(self):
        import tomllib

        edit = INSTALLER.plan_config_edit("", Path('/tmp/a "quoted"\\path/codex'))
        config = tomllib.loads(edit.after)
        command = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("mcrt_review_hook.py", command)
        self.assertEqual(shlex.split(command)[1], '/tmp/a "quoted"\\path/codex/mcrt_review_hook.py')

    def test_registration_is_idempotent_for_an_awkward_path(self):
        root = Path('/tmp/a "quoted"\\path/codex')
        once = INSTALLER.plan_config_edit("", root).after
        twice = INSTALLER.plan_config_edit(once, root)
        self.assertEqual(twice.after, once)


class LegacyRecordTest(unittest.TestCase):
    def managed(self) -> dict[str, bytes]:
        return INSTALLER._load_sources(INSTALLER._adapter_root())

    def legacy(self, tmp: Path, *, edited: bool = False):
        sources = self.managed()
        base = tmp / "codex"
        for name, data in sources.items():
            if not name.startswith("agents/"):
                continue
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"tampered" if edited else data)
        record = tmp / "record.json"
        record.write_text(json.dumps({"agent_hashes": {
            name.removeprefix("agents/"): INSTALLER._sha256(data)
            for name, data in sources.items() if name.startswith("agents/")
        }}), encoding="utf-8")
        config = tmp / "config.toml"
        config.write_text("[agents]\nmax_depth = 40\n", encoding="utf-8")
        return base, config, record, sources

    def test_a_previous_release_install_upgrades_to_file_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, config, record, sources = self.legacy(Path(tmp))
            edit, upgraded = INSTALLER._preflight(base, config, record, sources)
            self.assertEqual(upgraded["file_hashes"], {name: INSTALLER._sha256(data) for name, data in sources.items()})
            self.assertEqual(edit.before, "[agents]\nmax_depth = 40\n")

    def test_a_previous_release_install_with_an_edited_agent_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, config, record, sources = self.legacy(Path(tmp), edited=True)
            with self.assertRaises(ValueError):
                INSTALLER._preflight(base, config, record, sources)


if __name__ == "__main__":
    unittest.main()
