from __future__ import annotations

import importlib.util
import json
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


if __name__ == "__main__":
    unittest.main()
