"""Tests for scripts/install-claude.sh.

The script is exercised end to end against fixture release archives, with a
stub `curl` on PATH standing in for GitHub. Stubbing the transport rather than
the script's own logic is what makes these tests worth having: the interesting
failures are in argument handling, archive layout, and degradation when an asset
is absent, and none of those show up if the download is mocked away.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "install-claude.sh"
LATEST_VERSION = "0.9.9"
RELEASES_LATEST = (
    "https://api.github.com/repos/Monolith-INC/monolithic-code-review-toolkit/releases/latest"
)

# A stub that answers exactly the two shapes the installer uses: the releases API
# read (stdout) and an asset download (-o). An unknown asset exits 22, which is
# what curl itself returns for a 404 under -f.
CURL_STUB = f"""#!/usr/bin/env bash
url=""
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    http*) url="$1"; shift ;;
    *) shift ;;
  esac
done
if [ "$url" = "{RELEASES_LATEST}" ]; then
  cat "$MCRT_FIXTURES/latest.json"
  exit 0
fi
src="$MCRT_FIXTURES/${{url##*/}}"
[ -f "$src" ] || exit 22
if [ -n "$out" ]; then cp "$src" "$out"; else cat "$src"; fi
"""


def write_tar(path: Path, files: dict[str, str]) -> None:
    """Write a gzip tarball whose members are exactly `files`, paths verbatim."""
    staging = path.parent / f"{path.name}.staging"
    try:
        for name, contents in files.items():
            member = staging / name
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_text(contents, encoding="utf-8")
        with tarfile.open(path, "w:gz") as archive:
            for name in files:
                archive.add(staging / name, arcname=name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


class InstallClaudeScriptTestCase(unittest.TestCase):
    """Base fixture: a fake release directory plus a stub curl on PATH."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mcrt-install-claude-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.home = self.tmp / "home"
        self.home.mkdir()
        self.fixtures = self.tmp / "release"
        self.fixtures.mkdir()

        (self.fixtures / "latest.json").write_text(
            json.dumps({"tag_name": f"v{LATEST_VERSION}"}), encoding="utf-8"
        )
        self.write_release(LATEST_VERSION)

        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "curl"
        stub.write_text(CURL_STUB, encoding="utf-8")
        stub.chmod(0o755)
        self.bin_dir = bin_dir

    @staticmethod
    def orchestrator_members() -> dict[str, str]:
        """Mirror the real archive: the adapter plus the shared `core` runtime.

        The adapter resolves `core` as `parents[2]/core`, so the archive ships
        both and the staged layout has to preserve that relationship.
        """
        return {
            "adapters/claude/install_claude_adapter.py": "# installer\n",
            "adapters/claude/mcrt_poster_guard_hook.py": "from core.review_harness.gate import X\n",
            "adapters/claude/agents/mcrt-review-poster.md": "poster\n",
            "core/__init__.py": "",
            "core/review_harness/__init__.py": "",
            "core/review_harness/gate.py": "X = 1\n",
        }

    def write_release(self, version: str) -> None:
        prefix = f"monolithic-code-review-toolkit-{version}"
        write_tar(
            self.fixtures / f"{prefix}-claude.tar.gz",
            {
                "payload/.claude-plugin/plugin.json": json.dumps(
                    {"name": "monolithic-code-review-toolkit", "version": version}
                ),
                "payload/skills/review-setup/SKILL.md": "---\nname: review-setup\n---\n",
                "payload/skills/review-task/SKILL.md": "---\nname: review-task\n---\n",
                "bundle.json": "{}",
            },
        )
        write_tar(
            self.fixtures / f"{prefix}-claude-review-orchestrator.tar.gz",
            self.orchestrator_members(),
        )
        write_tar(
            self.fixtures / f"{prefix}-knowledge-adapter.tar.gz",
            {
                "adapters/knowledge/install_knowledge_adapter.py": "# installer\n",
                "adapters/knowledge/mcrt_knowledge_mcp.py": "# server\n",
                "adapters/knowledge/pyproject.toml": "[project]\n",
            },
        )

    def run_installer(self, **env_overrides: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.pop("MCRT_VERSION", None)
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin_dir}{os.pathsep}{env['PATH']}",
                "MCRT_FIXTURES": str(self.fixtures),
            }
        )
        env.update(env_overrides)
        return subprocess.run(
            ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=120
        )

    # Default install locations, mirroring the script's own defaults.
    @property
    def plugin_dir(self) -> Path:
        return self.home / ".claude" / "skills" / "monolithic-code-review-toolkit"

    @property
    def adapter_home(self) -> Path:
        return self.home / ".claude" / "mcrt"

    def manifest(self) -> dict:
        return json.loads((self.adapter_home / "install.json").read_text(encoding="utf-8"))


class SuccessfulInstallTest(InstallClaudeScriptTestCase):
    def test_installs_the_payload_and_stages_both_adapters(self):
        result = self.run_installer(MCRT_VERSION="0.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertTrue((self.plugin_dir / ".claude-plugin" / "plugin.json").is_file())
        self.assertTrue((self.plugin_dir / "skills" / "review-setup" / "SKILL.md").is_file())
        # `bundle.json` sits beside `payload/` in the archive and is release
        # metadata, not plugin content: extracting it would put an unexpected
        # file inside the discovered plugin root.
        self.assertFalse((self.plugin_dir / "bundle.json").exists())

        self.assertTrue(
            (self.adapter_home / "adapters" / "claude" / "install_claude_adapter.py").is_file()
        )
        self.assertTrue(
            (self.adapter_home / "adapters" / "claude" / "agents" / "mcrt-review-poster.md").is_file()
        )
        self.assertTrue(
            (self.adapter_home / "adapters" / "knowledge" / "install_knowledge_adapter.py").is_file()
        )

    def test_manifest_records_what_review_setup_needs(self):
        result = self.run_installer(MCRT_VERSION="0.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)

        manifest = self.manifest()
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["host"], "claude")
        self.assertEqual(manifest["version"], "0.9.9")
        self.assertEqual(manifest["plugin_root"], str(self.plugin_dir))
        self.assertTrue(manifest["python"])

        orchestrator = manifest["adapters"]["orchestrator"]
        self.assertEqual(
            orchestrator["installer"],
            str(self.adapter_home / "adapters" / "claude" / "install_claude_adapter.py"),
        )
        self.assertEqual(orchestrator["scope"], "project")
        self.assertFalse(orchestrator["requires_pip"])

        knowledge = manifest["adapters"]["knowledge"]
        self.assertEqual(
            knowledge["installer"],
            str(self.adapter_home / "adapters" / "knowledge" / "install_knowledge_adapter.py"),
        )
        # The one component with third-party dependencies. review-setup has to
        # know that before it offers to register the server, because installing
        # them is a separate consent.
        self.assertTrue(knowledge["requires_pip"])

    def test_every_manifest_installer_path_exists(self):
        self.run_installer(MCRT_VERSION="0.9.9")
        for name, adapter in self.manifest()["adapters"].items():
            with self.subTest(adapter=name):
                self.assertTrue(Path(adapter["installer"]).is_file())
                self.assertTrue(Path(adapter["root"]).is_dir())

    def test_resolves_the_latest_release_when_no_version_is_pinned(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest()["version"], LATEST_VERSION)

    def test_records_the_interpreter_it_was_given(self):
        self.run_installer(MCRT_VERSION="0.9.9", MCRT_PYTHON="/usr/bin/python3.13")
        self.assertEqual(self.manifest()["python"], "/usr/bin/python3.13")

    def test_installs_into_paths_containing_spaces(self):
        target = self.tmp / "with space" / "plugin"
        adapters = self.tmp / "with space" / "mcrt"
        result = self.run_installer(
            MCRT_VERSION="0.9.9",
            MCRT_CLAUDE_SKILLS_DIR=str(target),
            MCRT_CLAUDE_ADAPTER_DIR=str(adapters),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((target / ".claude-plugin" / "plugin.json").is_file())
        manifest = json.loads((adapters / "install.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["plugin_root"], str(target))

    def test_reinstall_replaces_the_previous_payload(self):
        self.run_installer(MCRT_VERSION="0.9.9")
        stale = self.plugin_dir / "skills" / "removed-skill" / "SKILL.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("---\nname: removed-skill\n---\n", encoding="utf-8")

        result = self.run_installer(MCRT_VERSION="0.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(stale.exists())
        self.assertTrue((self.plugin_dir / "skills" / "review-setup" / "SKILL.md").is_file())


class SharedRuntimeTest(InstallClaudeScriptTestCase):
    """The orchestrator's `core` runtime must survive staging.

    This is the failure worth a dedicated class: the adapter imports `core`, so
    a stage that drops it produces a poster guard that raises at import. The
    host treats a non-zero PreToolUse hook as a non-blocking error, so the
    approval gate the adapter exists to enforce would silently permit every
    guarded pull-request write.
    """

    def test_core_is_staged_where_the_adapter_resolves_it(self):
        result = self.run_installer(MCRT_VERSION="0.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)

        hook = self.adapter_home / "adapters" / "claude" / "mcrt_poster_guard_hook.py"
        self.assertTrue(hook.is_file())
        # The adapter computes its root as parents[2], so `core` has to sit two
        # levels above the hook file itself.
        self.assertEqual(hook.resolve().parents[2], self.adapter_home.resolve())
        self.assertTrue((self.adapter_home / "core" / "review_harness" / "gate.py").is_file())

    def test_the_staged_hook_can_actually_import_core(self):
        self.run_installer(MCRT_VERSION="0.9.9")
        hook = self.adapter_home / "adapters" / "claude" / "mcrt_poster_guard_hook.py"
        # Reproduce the adapter's own sys.path bootstrap and import for real,
        # rather than asserting on file layout alone.
        probe = subprocess.run(
            [
                "python3",
                "-c",
                "import sys, pathlib;"
                f"sys.path.insert(0, str(pathlib.Path({str(hook)!r}).resolve().parents[2]));"
                "import core.review_harness.gate",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_an_archive_missing_core_is_refused(self):
        members = self.orchestrator_members()
        for name in [key for key in members if key.startswith("core/")]:
            del members[name]
        write_tar(
            self.fixtures / "monolithic-code-review-toolkit-0.9.9-claude-review-orchestrator.tar.gz",
            members,
        )

        result = self.run_installer(MCRT_VERSION="0.9.9")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("would fail open", result.stderr)

    def test_restaging_refreshes_core(self):
        self.run_installer(MCRT_VERSION="0.9.9")
        stale = self.adapter_home / "core" / "review_harness" / "gate.py"
        stale.write_text("raise RuntimeError('stale')\n", encoding="utf-8")

        result = self.run_installer(MCRT_VERSION="0.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stale.read_text(encoding="utf-8"), "X = 1\n")


class AdapterSelectionTest(InstallClaudeScriptTestCase):
    def test_none_stages_no_adapters(self):
        result = self.run_installer(MCRT_VERSION="0.9.9", MCRT_ADAPTERS="none")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest()["adapters"], {})
        self.assertFalse((self.adapter_home / "adapters").exists())
        # The plugin itself still installs: adapters are the optional half.
        self.assertTrue((self.plugin_dir / ".claude-plugin" / "plugin.json").is_file())

    def test_a_single_adapter_can_be_selected(self):
        result = self.run_installer(MCRT_VERSION="0.9.9", MCRT_ADAPTERS="knowledge")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(self.manifest()["adapters"]), ["knowledge"])
        self.assertFalse((self.adapter_home / "adapters" / "claude").exists())

    def test_duplicates_and_whitespace_are_tolerated(self):
        result = self.run_installer(
            MCRT_VERSION="0.9.9", MCRT_ADAPTERS="knowledge, orchestrator, knowledge"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(self.manifest()["adapters"]), ["knowledge", "orchestrator"])

    def test_an_unknown_adapter_name_is_refused_before_anything_is_written(self):
        result = self.run_installer(MCRT_VERSION="0.9.9", MCRT_ADAPTERS="orchestrator,bogus")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown adapter 'bogus'", result.stderr)
        # A typo must not leave a half-install behind that looks finished.
        self.assertFalse(self.plugin_dir.exists())
        self.assertFalse((self.adapter_home / "install.json").exists())


class DegradationTest(InstallClaudeScriptTestCase):
    def test_a_missing_adapter_asset_warns_without_failing_the_install(self):
        (self.fixtures / "monolithic-code-review-toolkit-0.9.9-knowledge-adapter.tar.gz").unlink()

        result = self.run_installer(MCRT_VERSION="0.9.9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ships no knowledge adapter", result.stderr)

        self.assertTrue((self.plugin_dir / ".claude-plugin" / "plugin.json").is_file())
        # The manifest must describe what is actually on disk, so review-setup
        # never offers to run an installer that was never staged.
        self.assertEqual(sorted(self.manifest()["adapters"]), ["orchestrator"])

    def test_a_missing_payload_asset_fails_the_install(self):
        (self.fixtures / "monolithic-code-review-toolkit-0.9.9-claude.tar.gz").unlink()

        result = self.run_installer(MCRT_VERSION="0.9.9")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.adapter_home / "install.json").exists())

    def test_a_payload_without_skills_is_rejected(self):
        write_tar(
            self.fixtures / "monolithic-code-review-toolkit-0.9.9-claude.tar.gz",
            {"payload/.claude-plugin/plugin.json": "{}", "bundle.json": "{}"},
        )

        result = self.run_installer(MCRT_VERSION="0.9.9")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no skills found", result.stderr)


class ScriptContractTest(unittest.TestCase):
    """Invariants that hold without running the script."""

    def test_the_script_parses(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_it_fails_fast_like_the_cursor_installer(self):
        self.assertIn("set -euo pipefail", SCRIPT.read_text(encoding="utf-8"))

    def test_it_avoids_bash_4_only_builtins(self):
        # macOS still ships bash 3.2, and `curl | bash` runs whatever bash is
        # first on PATH. mapfile/readarray and associative arrays would fail
        # there at parse time, on the one platform hardest to test locally.
        # Comments are excluded: the script names these constructs to explain
        # why it avoids them.
        for number, line in enumerate(SCRIPT.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for builtin in ("mapfile", "readarray", "declare -A", "local -A"):
                with self.subTest(line=number, builtin=builtin):
                    self.assertNotIn(builtin, line, f"line {number}: {line.strip()}")

    def test_it_does_not_install_python_dependencies(self):
        # Staging is not wiring. A piped installer has no human to consent to a
        # pip install, so the knowledge adapter's dependencies are review-setup's
        # to ask about.
        body = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("pip install", body)


if __name__ == "__main__":
    unittest.main()
