from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ADAPTER / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


INSTALLER = load("install_knowledge_adapter.py", "install_knowledge_adapter")


def sources_json(root: str | None, tmp: Path) -> None:
    path = tmp / ".monolithic-code-review"
    path.mkdir(parents=True, exist_ok=True)
    (path / "sources.json").write_text(json.dumps({"version": 1, "knowledge": {"root": root}}), encoding="utf-8")


class ResolveRootTest(unittest.TestCase):
    def test_prefers_the_root_review_setup_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            sources_json("AI_Codex/Project_Knowledge", project)
            root, origin = INSTALLER.resolve_knowledge_root(project, None)
        self.assertEqual(root, project / "AI_Codex/Project_Knowledge")
        self.assertIn("sources.json", origin)

    def test_absolute_recorded_root_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            sources_json("/srv/knowledge", project)
            root, _ = INSTALLER.resolve_knowledge_root(project, None)
        self.assertEqual(root, Path("/srv/knowledge"))

    def test_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            sources_json("AI_Codex/Project_Knowledge", project)
            root, origin = INSTALLER.resolve_knowledge_root(project, tmp + "/elsewhere")
        self.assertEqual(root, Path(tmp).resolve() / "elsewhere")
        self.assertEqual(origin, "--knowledge-root")

    def test_falls_back_to_the_documented_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, origin = INSTALLER.resolve_knowledge_root(Path(tmp), None)
        self.assertEqual(root, Path(tmp).resolve() / ".monolithic-code-review/knowledge")
        self.assertEqual(origin, "default")

    def test_a_declined_store_is_an_error_not_a_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            sources_json(None, project)
            with self.assertRaises(ValueError) as caught:
                INSTALLER.resolve_knowledge_root(project, None)
        self.assertIn("review-setup", str(caught.exception))


class ConfigEditTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Path("/opt/mcrt/adapters/knowledge")
        self.knowledge = Path("/repo/.monolithic-code-review/knowledge")

    def test_appends_into_an_empty_config(self):
        edit = INSTALLER.plan_config_edit("", self.adapter, self.knowledge)
        self.assertEqual(edit.action, "append")
        entry = json.loads(edit.after)["mcpServers"]["mcrt-knowledge"]
        self.assertEqual(entry["env"]["MCRT_KNOWLEDGE_ROOT"], str(self.knowledge))
        self.assertIn(str(self.adapter / "mcrt_knowledge_mcp.py"), entry["args"])

    def test_preserves_other_servers(self):
        before = json.dumps({"mcpServers": {"linear": {"type": "streamable-http", "url": "https://x"}}})
        edit = INSTALLER.plan_config_edit(before, self.adapter, self.knowledge)
        servers = json.loads(edit.after)["mcpServers"]
        self.assertIn("linear", servers)
        self.assertIn("mcrt-knowledge", servers)

    def test_reinstalling_the_same_entry_is_a_no_op(self):
        first = INSTALLER.plan_config_edit("", self.adapter, self.knowledge)
        second = INSTALLER.plan_config_edit(first.after, self.adapter, self.knowledge)
        self.assertEqual(second.action, "none")
        self.assertEqual(second.after, first.after)

    def test_a_changed_knowledge_root_replaces_the_entry(self):
        first = INSTALLER.plan_config_edit("", self.adapter, self.knowledge)
        second = INSTALLER.plan_config_edit(first.after, self.adapter, Path("/repo/AI_Codex/Project_Knowledge"))
        self.assertEqual(second.action, "replace")

    def test_refuses_to_overwrite_an_unmanaged_entry(self):
        before = json.dumps({"mcpServers": {"mcrt-knowledge": {"command": "somethingelse"}}})
        with self.assertRaises(ValueError) as caught:
            INSTALLER.plan_config_edit(before, self.adapter, self.knowledge)
        self.assertIn("unmanaged", str(caught.exception))

    def test_rejects_malformed_json(self):
        with self.assertRaises(ValueError):
            INSTALLER.plan_config_edit("{not json", self.adapter, self.knowledge)

    def test_rejects_a_non_object_servers_key(self):
        with self.assertRaises(ValueError):
            INSTALLER.plan_config_edit(json.dumps({"mcpServers": []}), self.adapter, self.knowledge)


class RemovalTest(unittest.TestCase):
    def setUp(self):
        self.adapter = Path("/opt/mcrt/adapters/knowledge")
        self.installed = INSTALLER.plan_config_edit(
            json.dumps({"mcpServers": {"linear": {"url": "https://x"}}}),
            self.adapter,
            Path("/repo/knowledge"),
        ).after

    def test_removes_only_our_entry(self):
        edit = INSTALLER.plan_removal(self.installed, self.adapter)
        self.assertEqual(edit.action, "remove")
        servers = json.loads(edit.after)["mcpServers"]
        self.assertNotIn("mcrt-knowledge", servers)
        self.assertIn("linear", servers)

    def test_absent_entry_is_a_no_op(self):
        edit = INSTALLER.plan_removal(json.dumps({"mcpServers": {}}), self.adapter)
        self.assertEqual(edit.action, "none")

    def test_leaves_an_unmanaged_entry_alone(self):
        before = json.dumps({"mcpServers": {"mcrt-knowledge": {"command": "somethingelse"}}})
        with self.assertRaises(ValueError):
            INSTALLER.plan_removal(before, self.adapter)

    def test_drops_the_servers_key_when_it_empties(self):
        only_ours = INSTALLER.plan_config_edit("", self.adapter, Path("/repo/knowledge")).after
        edit = INSTALLER.plan_removal(only_ours, self.adapter)
        self.assertNotIn("mcpServers", json.loads(edit.after))


class CommandLineTest(unittest.TestCase):
    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_json("knowledge", Path(tmp))
            code = INSTALLER.main(["--project", tmp, "--dry-run"])
            self.assertEqual(code, 0)
            self.assertFalse((Path(tmp) / ".mcp.json").exists())

    def test_install_then_uninstall_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_json("knowledge", Path(tmp))
            config = Path(tmp) / ".mcp.json"

            self.assertEqual(INSTALLER.main(["--project", tmp]), 0)
            self.assertIn("mcrt-knowledge", json.loads(config.read_text())["mcpServers"])
            self.assertTrue((Path(tmp) / ".claude" / INSTALLER.RECORD_NAME).is_file())

            self.assertEqual(INSTALLER.main(["--project", tmp, "--uninstall"]), 0)
            self.assertNotIn("mcpServers", json.loads(config.read_text()))
            self.assertFalse((Path(tmp) / ".claude" / INSTALLER.RECORD_NAME).exists())

    def test_a_declined_store_blocks_the_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            sources_json(None, Path(tmp))
            self.assertEqual(INSTALLER.main(["--project", tmp]), 2)
            self.assertFalse((Path(tmp) / ".mcp.json").exists())


if __name__ == "__main__":
    unittest.main()
