"""The orchestrator archives must contain a runnable adapter.

Both adapters import ``core.review_harness``. If the release archive ships only
``adapters/<host>``, every hook dies with ModuleNotFoundError and exit 1 — which
both hosts treat as a *non-blocking* hook error, so every guarded write is
permitted unchecked. The archive contents are therefore part of the enforcement
contract, and this test packages them exactly as the release workflow declares.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
HOSTS = ("codex", "claude")


def packaged_paths(host: str) -> list[str]:
    """The repository paths the release workflow puts in one orchestrator archive."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = f"{host}-review-orchestrator.tar.gz"
    assert marker in workflow, f"{marker} is not packaged by the release workflow"
    tail = workflow[workflow.index(marker):]
    paths: list[str] = []
    for line in tail.splitlines()[1:]:
        token = line.strip().rstrip("\\").strip()
        if not token or token.startswith(("tar", "ls", "-", "#")) or token.endswith(":"):
            break
        for candidate in re.split(r"\s+", token):
            if candidate and (ROOT / candidate).exists():
                paths.append(candidate)
    return paths


class ReleaseArchiveTest(unittest.TestCase):
    def build(self, host: str, destination: Path) -> Path:
        paths = packaged_paths(host)
        self.assertTrue(paths, f"could not read the {host} archive contents from release.yml")
        archive = destination / f"{host}-review-orchestrator.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for path in paths:
                tar.add(ROOT / path, arcname=path, filter=self.skip_bytecode)
        return archive

    @staticmethod
    def skip_bytecode(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        return None if "__pycache__" in info.name else info

    def test_each_archive_ships_the_core_package(self):
        for host in HOSTS:
            with self.subTest(host=host):
                paths = packaged_paths(host)
                self.assertIn(f"adapters/{host}", paths)
                self.assertIn("core", paths)

    def test_each_extracted_adapter_imports_its_runtime(self):
        for host, module in (("codex", "mcrt_review_hook.py"), ("claude", "mcrt_poster_guard_hook.py")):
            with self.subTest(host=host):
                with tempfile.TemporaryDirectory() as tmp:
                    destination = Path(tmp)
                    archive = self.build(host, destination)
                    extracted = destination / "extracted"
                    with tarfile.open(archive) as tar:
                        tar.extractall(extracted, filter="data")
                    script = extracted / "adapters" / host / module
                    self.assertTrue(script.is_file(), f"{module} is missing from the archive")
                    result = subprocess.run(
                        [sys.executable, "-c", f"import runpy; runpy.run_path({str(script)!r}, run_name='_smoke')"],
                        cwd=extracted, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
