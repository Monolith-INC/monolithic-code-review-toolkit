from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ADAPTER = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ADAPTER / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


STORE = load("knowledge_store.py", "knowledge_store")


ARCHITECTURE = """---
id: 2-structure/architecture
tier: 2
type: structure
area: architecture
title: Architecture
read_when: "Deciding which layer owns a rule, or whether a dependency direction is allowed."
provenance: derived
sources:
  - docs/architecture.md
derived_from_commit: abc1234
updated: 2026-08-20
version: 3
status: current
supersedes: []
links:
  - "[[3-mechanics/testing]]"
---

## Summary

Adapters compile the portable plugin root into vendor payloads.

## Layout

The plugin root holds skills. Payload directories are build output.

## Rules

Skills must never import from adapters. The dependency direction is one way.

## Open questions

- none
"""

TESTING = """---
id: 3-mechanics/testing
tier: 3
type: mechanics
area: testing
title: Testing
read_when: "Deciding whether a change needs a test, or which runner to invoke."
provenance: stated
sources:
  - package.json
derived_from_commit: abc1234
updated: 2026-08-25
version: 1
status: current
supersedes: []
links: []
---

## Summary

Unit tests run through the standard library runner.

## Commands

Run the suite with the repository test script.

## Detail

Fixtures live beside the tests they serve.

## Open questions

- none
"""

DEPENDENCIES = "\n".join(
    [
        "# id: 3-mechanics/dependencies",
        "# tier: 3",
        "# type: mechanics",
        "# area: dependencies",
        "# title: Dependencies",
        "# read_when: Checking whether a package is already available before adding one.",
        "# provenance: derived",
        "# sources: package.json",
        "# updated: 2026-08-25",
        "# version: 1",
        "# status: current",
        "name\tversion\tkind",
        "pytest\t8.0.0\tdev",
        "",
    ]
)


def build_store(tmp: str) -> "STORE.KnowledgeStore":
    root = Path(tmp) / "knowledge"
    (root / "2-structure").mkdir(parents=True)
    (root / "3-mechanics").mkdir(parents=True)
    (root / "2-structure" / "architecture.md").write_text(ARCHITECTURE, encoding="utf-8")
    (root / "3-mechanics" / "testing.md").write_text(TESTING, encoding="utf-8")
    (root / "3-mechanics" / "dependencies.tsv").write_text(DEPENDENCIES, encoding="utf-8")
    return STORE.KnowledgeStore(root)


class CatalogTest(unittest.TestCase):
    def test_catalog_omits_superseded_units_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            path = store.root / "2-structure" / "architecture.md"
            path.write_text(path.read_text().replace("status: current", "status: superseded"))
            rows = store.catalog()
        self.assertNotIn("2-structure/architecture", [row["id"] for row in rows])
    def test_returns_routing_rows_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = build_store(tmp).catalog()
        self.assertEqual(
            [row["id"] for row in rows],
            ["2-structure/architecture", "3-mechanics/dependencies", "3-mechanics/testing"],
        )
        for row in rows:
            self.assertNotIn("content", row)
            self.assertTrue(row["read_when"])

    def test_facets_filter_the_routing_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            by_type = store.catalog(type="structure")
            by_prefix = store.catalog(path_prefix="3-mechanics")
            by_date = store.catalog(updated_after="2026-08-21")
        self.assertEqual([row["id"] for row in by_type], ["2-structure/architecture"])
        self.assertEqual(len(by_prefix), 2)
        self.assertEqual([row["id"] for row in by_date], ["3-mechanics/dependencies", "3-mechanics/testing"])

    def test_written_catalog_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            first = store.write_catalog().read_bytes()
            second = store.write_catalog().read_bytes()
        self.assertEqual(first, second)
        self.assertTrue(first.decode().startswith("id\ttype\tarea\ttitle\tpath\tprovenance\tupdated\tread_when"))

    def test_manifest_is_not_indexed_as_a_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            (store.root / STORE.MANIFEST_NAME).write_text("# Knowledge manifest\n", encoding="utf-8")
            rows = store.catalog()
        self.assertEqual([row["id"] for row in rows], [
            "2-structure/architecture",
            "3-mechanics/dependencies",
            "3-mechanics/testing",
        ])


class FindTest(unittest.TestCase):
    def test_returns_locations_with_matched_terms_not_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            hits, guidance = build_store(tmp).find("dependency direction")
        self.assertEqual(guidance, {})
        self.assertTrue(hits)
        top = hits[0]
        self.assertEqual(top.unit_id, "2-structure/architecture")
        self.assertIn("dependency", top.matched_terms)
        self.assertTrue(top.anchor)
        self.assertLessEqual(top.start_line, top.end_line)
        self.assertLess(len(top.snippet), 300)

    def test_ordering_is_deterministic_across_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            first, _ = store.find("tests")
            second, _ = store.find("tests")
        self.assertEqual(
            [(hit.unit_id, hit.anchor, hit.score) for hit in first],
            [(hit.unit_id, hit.anchor, hit.score) for hit in second],
        )

    def test_matched_terms_expose_a_partially_matching_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            hits, _ = build_store(tmp).find("fixtures nonexistentterm")
        self.assertTrue(hits)
        self.assertEqual(hits[0].matched_terms, ["fixtures"])

    def test_empty_result_returns_guidance_rather_than_emptiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            hits, guidance = build_store(tmp).find("kubernetes helm chart")
        self.assertEqual(hits, [])
        self.assertIn("reason", guidance)
        self.assertIn("structure", guidance["facets"]["type"])
        self.assertEqual(guidance["unit_count"], 3)
        self.assertTrue(guidance["nearest_units"])

    def test_guidance_offers_near_miss_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, guidance = build_store(tmp).find("architectur")
        self.assertIn("architecture", guidance["near_miss_terms"])

    def test_limit_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            hits, _ = build_store(tmp).find("the", limit=1)
        self.assertLessEqual(len(hits), 1)


class FetchTest(unittest.TestCase):
    def test_long_first_line_never_exceeds_the_token_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            (store.root / "long.md").write_text("x" * 100, encoding="utf-8")
            result = store.fetch("long", max_tokens=10)
        self.assertLessEqual(STORE.estimate_tokens(result["content"]), 10)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["continuation"]["start_line"], 1)
        self.assertGreater(result["continuation"]["start_column"], 0)
    def test_returns_content_with_a_version_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_store(tmp).fetch("3-mechanics/testing")
        self.assertIn("Fixtures live beside", result["content"])
        self.assertEqual(len(result["version"]), 12)
        self.assertEqual(result["provenance"], "stated")
        self.assertFalse(result["truncated"])

    def test_anchor_narrows_to_one_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_store(tmp).fetch("2-structure/architecture", anchor="rules")
        self.assertIn("dependency direction is one way", result["content"])
        self.assertNotIn("Payload directories", result["content"])

    def test_unknown_anchor_names_the_available_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(STORE.StoreError) as caught:
                build_store(tmp).fetch("2-structure/architecture", anchor="nope")
        self.assertIn("summary", str(caught.exception))

    def test_over_budget_fetch_truncates_with_a_continuation_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_store(tmp).fetch("2-structure/architecture", max_tokens=10)
        self.assertTrue(result["truncated"])
        self.assertIsNotNone(result["continuation"])
        self.assertGreater(result["continuation"]["remaining_lines"], 0)
        self.assertLessEqual(STORE.estimate_tokens(result["content"]), 12)

    def test_truncated_anchor_continuation_resumes_after_the_first_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            first = store.fetch("2-structure/architecture", anchor="rules", max_tokens=8)
            continuation = first["continuation"]
            self.assertIsNotNone(continuation)
            resumed = store.fetch(
                continuation["id"],
                anchor=continuation["anchor"],
                start_line=continuation["start_line"],
                max_tokens=100,
            )
        self.assertNotIn(first["content"], resumed["content"])
        self.assertIn("Open questions", resumed["content"])

    def test_unknown_unit_suggests_nearest_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(STORE.UnknownUnit) as caught:
                build_store(tmp).fetch("3-mechanics/testin")
        self.assertIn("3-mechanics/testing", caught.exception.nearest)


class LinksTest(unittest.TestCase):
    def test_outbound_links_are_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            edges = build_store(tmp).links("2-structure/architecture", direction="out")
        self.assertEqual(edges["out"], ["3-mechanics/testing"])

    def test_backlinks_are_reachable_only_through_this_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            edges = build_store(tmp).links("3-mechanics/testing", direction="in")
        self.assertEqual(edges["in"], ["2-structure/architecture"])

    def test_rejects_an_unknown_direction(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(STORE.StoreError):
                build_store(tmp).links("3-mechanics/testing", direction="sideways")


class WriteTest(unittest.TestCase):
    def test_writes_refresh_the_adapter_free_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            store.write_catalog()
            store.put("2-structure/topology", ARCHITECTURE.replace("2-structure/architecture", "2-structure/topology"), STORE.NEW_VERSION)
            catalog = (store.root / STORE.CATALOG_NAME).read_text()
        self.assertIn("2-structure/topology", catalog)
    def test_put_creates_a_unit_and_bumps_the_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            body = ARCHITECTURE.replace("2-structure/architecture", "2-structure/topology")
            store.put("2-structure/topology", body, STORE.NEW_VERSION)
            unit = store.unit("2-structure/topology")
        self.assertEqual(unit.fields["version"], "1")
        self.assertTrue(unit.path.name.endswith(".md"))

    def test_put_round_trips_the_version_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            before = store.fetch("3-mechanics/testing")["version"]
            written = store.put("3-mechanics/testing", TESTING, before)
            after = store.fetch("3-mechanics/testing")["version"]
        self.assertEqual(written["version"], after)
        self.assertNotEqual(before, after)

    def test_a_writer_that_loses_the_race_gets_a_version_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = build_store(tmp)
            second = STORE.KnowledgeStore(first.root)
            version = second.fetch("3-mechanics/testing")["version"]
            check_version = second._check_version

            def race(unit_id, if_version):
                previous = check_version(unit_id, if_version)
                first.put("3-mechanics/testing", TESTING.replace("Fixtures", "Updated fixtures"), version)
                return previous

            with patch.object(second, "_check_version", side_effect=race):
                with self.assertRaises(STORE.VersionConflict):
                    second.put("3-mechanics/testing", TESTING.replace("Fixtures", "Stale fixtures"), version)
            self.assertIn("Updated fixtures", first.fetch("3-mechanics/testing")["content"])

    def test_put_rejects_frontmatter_for_a_different_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            with self.assertRaises(STORE.StoreError) as caught:
                store.put("2-structure/topology", ARCHITECTURE, STORE.NEW_VERSION)
        self.assertIn("frontmatter id", str(caught.exception))

    def test_stale_if_version_returns_the_current_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            with self.assertRaises(STORE.VersionConflict) as caught:
                store.put("3-mechanics/testing", TESTING, "000000000000")
        payload = caught.exception.payload()
        self.assertIn("Fixtures live beside", payload["current_content"])
        self.assertEqual(payload["expected_version"], "000000000000")
        self.assertEqual(len(payload["current_version"]), 12)

    def test_creating_without_the_new_sentinel_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            with self.assertRaises(STORE.StoreError) as caught:
                store.put("2-structure/brand-new", ARCHITECTURE, "deadbeefcafe")
        self.assertIn("new", str(caught.exception))

    def test_patch_replaces_exactly_one_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            version = store.fetch("2-structure/architecture")["version"]
            store.patch("2-structure/architecture", "one way", "unidirectional", version)
            content = store.fetch("2-structure/architecture")["content"]
            self.assertIn("unidirectional", content)
            self.assertEqual(store.unit("2-structure/architecture").fields["version"], "4")

    def test_failed_patch_returns_the_surrounding_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            version = store.fetch("2-structure/architecture")["version"]
            with self.assertRaises(STORE.PatchMismatch) as caught:
                store.patch("2-structure/architecture", "Skills must never import from vendors.", "x", version)
        payload = caught.exception.payload()
        self.assertEqual(payload["occurrences"], 0)
        self.assertIn("Skills must never import from adapters.", payload["context"])

    def test_ambiguous_patch_reports_the_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            version = store.fetch("2-structure/architecture")["version"]
            with self.assertRaises(STORE.PatchMismatch) as caught:
                store.patch("2-structure/architecture", "\n", "x", version)
        self.assertGreater(caught.exception.occurrences, 1)
        self.assertIn("must match exactly once", str(caught.exception))

    def test_add_appends_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            version = store.fetch("3-mechanics/testing")["version"]
            store.add("3-mechanics/testing", "## Addendum\n\nCoverage gate is advisory.", version)
            content = store.fetch("3-mechanics/testing")["content"]
        self.assertIn("Fixtures live beside", content)
        self.assertIn("Coverage gate is advisory.", content)

    def test_tsv_unit_keeps_its_comment_header_on_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            version = store.fetch("3-mechanics/dependencies")["version"]
            store.add("3-mechanics/dependencies", "ruff\t0.5.0\tdev", version)
            unit = store.unit("3-mechanics/dependencies")
        self.assertEqual(unit.fmt, "tsv")
        self.assertEqual(unit.fields["version"], "2")
        self.assertIn("ruff\t0.5.0\tdev", unit.body)
        self.assertTrue(unit.raw.startswith("# id: 3-mechanics/dependencies"))

    def test_traversal_outside_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            for unit_id in ("../escape", "/etc/passwd", "2-structure/../../escape"):
                with self.assertRaises(STORE.StoreError):
                    store.put(unit_id, ARCHITECTURE, STORE.NEW_VERSION)

    def test_external_edits_are_picked_up_without_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = build_store(tmp)
            self.assertEqual(len(store.units), 3)
            (store.root / "2-structure" / "domain-model.md").write_text(
                ARCHITECTURE.replace("2-structure/architecture", "2-structure/domain-model"),
                encoding="utf-8",
            )
            self.assertEqual(len(store.units), 4)


class ParsingTest(unittest.TestCase):
    def test_frontmatter_round_trips_through_the_dumper(self):
        fields, body = STORE.parse_frontmatter(ARCHITECTURE)
        reparsed, _ = STORE.parse_frontmatter(STORE.dump_frontmatter(fields) + body)
        self.assertEqual(fields, reparsed)

    def test_empty_and_inline_lists_both_parse(self):
        fields, _ = STORE.parse_frontmatter("---\nlinks: []\nsources: [a.json, b.json]\nsupersedes:\n---\n\nbody\n")
        self.assertEqual(fields["links"], [])
        self.assertEqual(fields["sources"], ["a.json", "b.json"])
        self.assertEqual(fields["supersedes"], [])

    def test_accents_are_folded_for_search(self):
        self.assertEqual(STORE.tokenize("Configuração"), STORE.tokenize("configuracao"))

    def test_headings_inside_fenced_blocks_are_not_anchors(self):
        text = "---\nid: x\ntype: rules\n---\n\n## Real\n\n```text\n## Not a heading\n```\n"
        fields, body = STORE.parse_frontmatter(text)
        unit = STORE.Unit("x", Path("x.md"), "md", fields, body, text, "0" * 12)
        self.assertEqual([section.anchor for section in unit.sections()], ["real"])


if __name__ == "__main__":
    unittest.main()
