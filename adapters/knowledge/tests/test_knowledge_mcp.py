"""Contract tests for the MCP tool surface.

These skip when the `mcp` SDK is absent so a contributor without the adapter's
dependencies still gets a green store suite. CI installs them, so the skip never
hides a regression there.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

ADAPTER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADAPTER))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_knowledge_store import build_store  # noqa: E402

try:
    os.environ.setdefault("MCRT_KNOWLEDGE_ROOT", tempfile.gettempdir())
    import mcrt_knowledge_mcp as server  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without the SDK
    server = None
    _REASON = f"mcp SDK not installed ({exc.name}); install adapters/knowledge to run these"

READ_TOOLS = ("knowledge_catalog", "knowledge_find", "knowledge_fetch", "knowledge_links")
WRITE_TOOLS = ("knowledge_put", "knowledge_patch", "knowledge_add")


def call(name: str, **arguments) -> str:
    result = asyncio.run(server.mcp.call_tool(name, arguments))
    blocks = result.content if hasattr(result, "content") else result[0]
    return "\n".join(getattr(block, "text", "") for block in blocks)


@unittest.skipIf(server is None, globals().get("_REASON", "mcp SDK not installed"))
class ToolSurfaceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = build_store(self._tmp.name)
        server.set_store(self.store)

    def tearDown(self):
        server.set_store(None)
        self._tmp.cleanup()

    def tools(self):
        return {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}

    def test_exposes_exactly_four_reads_and_three_writes(self):
        self.assertEqual(sorted(self.tools()), sorted(READ_TOOLS + WRITE_TOOLS))

    def test_read_tools_are_annotated_read_only(self):
        tools = self.tools()
        for name in READ_TOOLS:
            self.assertTrue(tools[name].annotations.read_only_hint, name)
            self.assertFalse(tools[name].annotations.destructive_hint, name)
        for name in WRITE_TOOLS:
            self.assertFalse(tools[name].annotations.read_only_hint, name)

    def test_every_tool_describes_when_to_reach_for_it(self):
        for name, tool in self.tools().items():
            self.assertTrue(tool.description, name)
            self.assertGreater(len(tool.description), 120, name)

    def test_read_descriptions_state_the_cost_ladder(self):
        tools = self.tools()
        self.assertIn("RUNG 1 OF 3", tools["knowledge_catalog"].description)
        self.assertIn("RUNG 2 OF 3", tools["knowledge_find"].description)
        self.assertIn("RUNG 3 OF 3", tools["knowledge_fetch"].description)

    def test_input_schemas_are_flat_and_faceted(self):
        schema = self.tools()["knowledge_find"].input_schema
        self.assertNotIn("params", schema["properties"])
        self.assertEqual(
            sorted(schema["properties"]), ["area", "limit", "path_prefix", "status", "terms", "type"]
        )
        self.assertEqual(schema["required"], ["terms"])

    def test_catalog_routes_without_returning_content(self):
        text = call("knowledge_catalog")
        self.assertIn("2-structure/architecture", text)
        self.assertIn("read_when", text)
        self.assertNotIn("Skills must never import", text)

    def test_find_reports_matched_terms(self):
        text = call("knowledge_find", terms="dependency direction")
        self.assertIn("matched terms:", text)
        self.assertIn("2-structure/architecture", text)

    def test_find_without_hits_returns_guidance(self):
        text = call("knowledge_find", terms="kubernetes helm")
        self.assertIn("No hits", text)
        self.assertIn("Available `type`", text)
        self.assertIn("Reformulate", text)

    def test_fetch_returns_a_version_token(self):
        text = call("knowledge_fetch", id="3-mechanics/testing")
        self.assertIn("version `", text)
        self.assertIn("Fixtures live beside", text)

    def test_fetch_truncation_is_explicit(self):
        text = call("knowledge_fetch", id="2-structure/architecture", max_tokens=50)
        self.assertIn("truncated at the token ceiling", text)
        self.assertIn("Continue with start_line=", text)

    def test_unknown_unit_suggests_the_nearest_ids(self):
        text = call("knowledge_fetch", id="3-mechanics/testin")
        self.assertIn("Closest ids", text)
        self.assertIn("3-mechanics/testing", text)

    def test_links_reports_backlinks(self):
        text = call("knowledge_links", id="3-mechanics/testing", direction="in")
        self.assertIn("referenced by: `2-structure/architecture`", text)

    def test_stale_write_returns_the_current_content_for_a_same_turn_retry(self):
        text = call("knowledge_put", id="3-mechanics/testing", content="x", if_version="000000000000")
        self.assertIn("version_conflict", text)
        self.assertIn("Fixtures live beside", text)

    def test_failed_patch_returns_surrounding_text(self):
        version = self.store.fetch("2-structure/architecture")["version"]
        text = call(
            "knowledge_patch",
            id="2-structure/architecture",
            old="Skills must never import from vendors.",
            new="x",
            if_version=version,
        )
        self.assertIn("patch_mismatch", text)
        self.assertIn("Skills must never import from adapters.", text)

    def test_successful_write_returns_the_next_version_token(self):
        version = self.store.fetch("3-mechanics/testing")["version"]
        text = call("knowledge_add", id="3-mechanics/testing", content="## Addendum", if_version=version)
        self.assertIn("Appended to", text)
        self.assertIn("New version token:", text)

    def test_assumed_units_are_flagged_as_uncitable(self):
        unit = (self.store.root / "3-mechanics" / "testing.md").read_text()
        (self.store.root / "3-mechanics" / "testing.md").write_text(
            unit.replace("provenance: stated", "provenance: assumed"), encoding="utf-8"
        )
        text = call("knowledge_fetch", id="3-mechanics/testing")
        self.assertIn("INCONCLUSIVE", text)


if __name__ == "__main__":
    unittest.main()
