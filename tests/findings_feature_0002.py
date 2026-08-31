"""Executable reproductions of the review findings on FEATURE-0002.

Every test here **fails on the branch as reviewed** and passes once the finding
it encodes is fixed. That is the point of the file: `tests/test_review_harness.py`
passes with all of these defects present, so a green suite is not evidence that
any of them was addressed.

Each test names the finding in its docstring and asserts the *desired* behaviour,
never the current behaviour — so a fix flips it without the test needing an edit,
and a partial fix stays red.

    pnpm test:findings

Named `findings_*` rather than `test_*` on purpose: `unittest discover` would
otherwise pick it up into the repository suite, and because the suites are
chained, a red one there stops the Codex, Claude and knowledge suites from
running at all — hiding ordinary regressions behind known ones. CI runs this as
its own job instead.

Read the failure list as a checklist. When it is empty, the findings are closed.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from core.review_harness.checkpoints import (
    CheckpointError,
    abandon,
    authorize,
    create,
    directory,
    record_outcome,
)
from core.review_harness import contracts as contracts_module
from core.review_harness.contracts import ContractError, binding_digest, migrate_sources_v1, validate_sources
from core.review_harness.gate import evaluate_action
from core.review_harness.schemas import sources_schema

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str, name: str):
    """Load an adapter module by path; they are scripts, not importable packages."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CODEX_HOOK = load("adapters/codex/mcrt_review_hook.py", "_findings_codex_hook")
CLAUDE_HOOK = load("adapters/claude/mcrt_poster_guard_hook.py", "_findings_claude_hook")
CLAUDE_INSTALLER = load("adapters/claude/install_claude_adapter.py", "_findings_claude_installer")
CODEX_INSTALLER = load("adapters/codex/install_codex_adapter.py", "_findings_codex_installer")


def sources() -> dict:
    """A valid v2 document binding one MCP write tool and one CLI read."""
    return {
        "version": 2,
        "scm": {
            "owner": "acme",
            "repo": "widgets",
            "capabilities": {
                "post_inline_comment": {
                    "kind": "mcp_tool", "server": "github", "tool": "post_comment",
                    "access": "write", "effect": "scm.comment.create",
                },
            },
            "unsupported": [],
        },
        "tracker": {"capabilities": {}, "unsupported": ["fetch_work_item"]},
    }


def workspace_with(tmp: str, approved: list[str]) -> tuple[Path, Path, dict]:
    """A workspace carrying valid v2 sources and one approved checkpoint."""
    root = Path(tmp)
    config = root / ".monolithic-code-review"
    config.mkdir(parents=True, exist_ok=True)
    document = sources()
    (config / "sources.json").write_text(json.dumps(document), encoding="utf-8")
    identity = {
        "workspace": str(root),
        "repository": "acme/widgets",
        "pull_request_id": "42",
        "binding_digest": binding_digest(document),
    }
    return root, create(root, identity, approved), identity


class GateTest(unittest.TestCase):
    def test_a_terminal_checkpoint_cannot_be_reopened(self):
        """gate.py:29 accepts 'completed'.

        The feature's own tech spec says "A terminal checkpoint cannot resume or
        silently reopen", and `checkpoints.abandon` enforces exactly that. The
        gate does not, so an approved-but-unattempted finding stays postable
        indefinitely after the run has ended.
        """
        checkpoint = {
            "status": "completed",
            "identity": {"workspace": "/w", "repository": "a/b", "pull_request_id": "1", "binding_digest": "d"},
            "approved_finding_ids": ["f1"],
            "attempted_finding_ids": [],
        }
        event = {
            "mcrt": True, "finding_ids": ["f1"], "workspace": "/w", "repository": "a/b",
            "pull_request_id": "1", "binding_digest": "d",
        }
        self.assertFalse(evaluate_action(checkpoint, event).allowed)

    def test_a_non_poster_role_is_denied(self):
        """gate.py:47 treats None as "identity unavailable → allow", and the Codex
        adapter maps every non-poster agent onto None (mcrt_review_hook.py:56), so
        "only the poster may use an approval" can never fire from that host."""
        checkpoint = {
            "status": "approved",
            "identity": {"workspace": "/w", "repository": "a/b", "pull_request_id": "1", "binding_digest": "d"},
            "approved_finding_ids": ["f1"],
            "attempted_finding_ids": [],
        }
        event = {
            "mcrt": True, "finding_ids": ["f1"], "workspace": "/w", "repository": "a/b",
            "pull_request_id": "1", "binding_digest": "d", "role": "validator",
        }
        self.assertFalse(evaluate_action(checkpoint, event).allowed)


class CheckpointTest(unittest.TestCase):
    def test_every_approved_finding_can_be_posted(self):
        """checkpoints.py:116 writes status='attempting', which the gate rejects.

        On Claude nothing ever transitions out of 'attempting' — the installer
        registers no PostToolUse hook — so only the first approved finding of a
        run can ever be posted. The rest are refused with a message claiming they
        were never approved.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root, path, identity = workspace_with(tmp, ["f1", "f2"])
            event = dict(identity, mcrt=True, finding_ids=["f1"], tool_use_id="post-f1")
            self.assertTrue(authorize(path, event).allowed)

            second = dict(identity, mcrt=True, finding_ids=["f2"], tool_use_id="post-f2")
            decision = authorize(path, second)
        self.assertTrue(decision.allowed, decision.reason)

    def test_a_stale_lock_does_not_wedge_recovery(self):
        """checkpoints.py:46 — the lock carries no pid, timestamp or staleness check.

        A hook killed at its 5s timeout never runs `finally: lock.unlink()`. After
        that, authorize, resume *and* abandon all raise, so the documented recovery
        path ("inspect, resume, abandon") leaves only inspect. At minimum abandon
        must be able to force past a stale lock.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _, path, _ = workspace_with(tmp, ["f1"])
            path.with_suffix(path.suffix + ".lock").touch()
            try:
                abandon(path, "operator recovery after a killed hook")
            except CheckpointError as error:
                self.fail(f"a stale lock made the run unrecoverable: {error}")

    def test_record_outcome_refuses_a_terminal_checkpoint(self):
        """checkpoints.py:122 has no terminal guard, so it flips an abandoned
        checkpoint to 'completed' and appends an outcome to a closed run."""
        with tempfile.TemporaryDirectory() as tmp:
            _, path, _ = workspace_with(tmp, ["f1"])
            abandon(path, "operator stopped the run")
            with self.assertRaises(CheckpointError):
                record_outcome(path, "tool-use-1", True)

    def test_the_active_checkpoint_is_chosen_regardless_of_filename(self):
        """mcrt_review_hook.py:29 (and mcrt_poster_guard_hook.py:110) use
        sorted(...)[-1]. Filenames are `checkpoint-{uuid4().hex}.json`, so
        lexicographic order is noise. Nothing deletes terminal checkpoints, and
        create() only refuses *active* ones, so they accumulate — and the wrong
        one is selected roughly half the time.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root, path, _ = workspace_with(tmp, ["f1"])
            live = json.loads(path.read_text(encoding="utf-8"))

            folder = directory(root)
            low = folder / "checkpoint-0000000000000000.json"
            high = folder / "checkpoint-ffffffffffffffff.json"
            path.rename(low)
            high.write_text(json.dumps(dict(live, status="abandoned"), indent=2), encoding="utf-8")

            selected = CODEX_HOOK._checkpoint(root)
        self.assertEqual(selected, low, "selected the abandoned checkpoint over the approved one")


class ContractsTest(unittest.TestCase):
    def test_a_non_object_capability_map_raises_contract_error(self):
        """contracts.py:123 evaluates set(scm.get("capabilities")) before the
        isinstance check three lines below, so a non-iterable value raises
        TypeError. Neither hook catches that — both catch ContractError — so the
        hook dies with a traceback and exit 1, which both hosts treat as a
        non-blocking error. The write proceeds. The spec says malformed v2
        documents must deny.
        """
        document = {
            "version": 2,
            "scm": {"capabilities": 5, "unsupported": []},
            "tracker": {"capabilities": {}, "unsupported": []},
        }
        with self.assertRaises(ContractError):
            validate_sources(document)

    def test_migration_refuses_command_substitution(self):
        """contracts.py:183 tests for the three-character sequence "$(`" instead
        of "$(" and "`" separately. Command substitution therefore migrates into a
        binding the docs call validated."""
        value = {
            "version": 1,
            "scm": {"capabilities": {"post_inline_comment": "gh pr comment 1 --body $(cat /etc/passwd)"}, "unsupported": []},
            "tracker": {"capabilities": {}, "unsupported": []},
        }
        migrated, diagnostics = migrate_sources_v1(value)
        self.assertIsNone(migrated, f"command substitution survived migration: {migrated}")
        self.assertTrue(diagnostics)

    def test_migration_refuses_backticks_and_composition(self):
        """Same defect, the other shapes: backticks, && and redirection."""
        for raw in (
            "gh pr comment 1 --body `whoami`",
            "gh pr comment 1 --body x && rm -rf /tmp/x",
            "gh pr comment 1 --body x > /tmp/out",
        ):
            with self.subTest(raw=raw):
                value = {
                    "version": 1,
                    "scm": {"capabilities": {"post_inline_comment": raw}, "unsupported": []},
                    "tracker": {"capabilities": {}, "unsupported": []},
                }
                migrated, diagnostics = migrate_sources_v1(value)
                self.assertIsNone(migrated, f"{raw!r} survived migration")
                self.assertTrue(diagnostics)


class CodexHookTest(unittest.TestCase):
    def test_a_non_poster_agent_is_not_reported_as_unknown_identity(self):
        """mcrt_review_hook.py:56 collapses mcrt_review_validator, the root session
        and a plain user shell all onto role=None, which the gate reads as "host
        identity unavailable" and allows. The adapter must distinguish "not the
        poster" from "no identity available"."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = workspace_with(tmp, ["f1"])
            payload = {
                "hook_event_name": "PreToolUse",
                "cwd": str(root),
                "agent_type": "mcrt_review_validator",
                "tool_name": "mcp__github__post_comment",
                "tool_input": {"mcrt_finding_ids": ["f1"], "pull_request_id": "42"},
            }
            reason = CODEX_HOOK.evaluate(payload)
        self.assertIsNotNone(reason, "a non-poster agent consumed an approval")

    def test_post_tool_use_ignores_an_unrelated_tool_call(self):
        """mcrt_review_hook.py:83 records succeeded=True for whatever tool call
        runs next while the checkpoint is 'attempting' — ignoring tool name,
        tool_use_id and tool_response. With matcher=".*" the next Read closes the
        run out as a success, so a post that actually failed is recorded as
        delivered and can never be retried."""
        with tempfile.TemporaryDirectory() as tmp:
            root, path, identity = workspace_with(tmp, ["f1"])
            authorize(path, dict(identity, mcrt=True, finding_ids=["f1"], tool_use_id="the-authorized-post"))

            payload = {
                "hook_event_name": "PostToolUse",
                "cwd": str(root),
                "tool_name": "Read",
                "tool_use_id": "an-unrelated-read",
                "tool_response": {"error": "file not found"},
            }
            original = sys.stdin
            sys.stdin = _Stdin(json.dumps(payload))
            try:
                CODEX_HOOK.main()
            finally:
                sys.stdin = original

            outcomes = json.loads(path.read_text(encoding="utf-8")).get("post_outcomes", [])
        self.assertEqual(outcomes, [], f"an unrelated tool call was recorded as the post's outcome: {outcomes}")


class ClaudeHookTest(unittest.TestCase):
    def test_the_default_matcher_covers_a_bound_mcp_write_tool(self):
        """install_claude_adapter.py:22 still hard-codes the tool surface, but the
        guarded surface is now data-driven from sources.json. mcp__github__post_comment
        — the tool this feature's own docs, tests and fixtures use — matches none of
        the alternatives, so on a default install the event never reaches the hook
        and the whole v2 branch is dead code."""
        matcher = CLAUDE_INSTALLER.DEFAULT_HOOK_MATCHER
        self.assertTrue(
            re.search(matcher, "mcp__github__post_comment"),
            f"matcher {matcher!r} never routes the bound write tool to the guard",
        )

    def test_a_local_write_carrying_a_marker_is_not_blocked(self):
        """mcrt_poster_guard_hook.py:152 — under v2 the marker check runs before any
        narrowing, so *any* tool whose content/body/text/command mentions
        [mcrt:...] is refused. The orchestrator cannot write its own findings
        report, or build a comment body with a heredoc. Gate on the tool, then
        check markers."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = workspace_with(tmp, ["f1"])
            reason = CLAUDE_HOOK.evaluate(
                "Write",
                {"file_path": str(root / "report.md"), "content": "Finding [mcrt:f1] is real"},
                root,
            )
        self.assertIsNone(reason, f"writing a local file was blocked: {reason}")

    def test_a_cli_post_can_be_authorized(self):
        """mcrt_poster_guard_hook.py:138 reads pull_request_id only from tool_input
        keys. A Bash payload carries `command`, never `pull_request_id`, so the id
        resolves to "" and never matches the checkpoint. Since the v2 branch
        short-circuits before the v1 fallback, a project on v2 with a command-kind
        write binding can never post anything."""
        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = workspace_with(tmp, ["f1"])
            reason = CLAUDE_HOOK.evaluate(
                "Bash",
                {"command": "gh pr comment 42 --body 'the issue [mcrt:f1] is real'"},
                root,
            )
        self.assertIsNone(reason, f"an approved CLI post was refused: {reason}")


class ReleaseTest(unittest.TestCase):
    def test_the_orchestrator_archives_ship_the_core_package(self):
        """The adapters now import core.review_harness, but release.yml packages
        only adapters/codex and adapters/claude. On a tarball install every hook
        dies with ModuleNotFoundError and exit 1 — a *non-blocking* hook error on
        both hosts — so every MCRT write is permitted unchecked. That is the exact
        bypass docs/review-harness-contracts.md says cannot happen.
        """
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        for vendor in ("codex", "claude"):
            marker = f"{vendor}-review-orchestrator.tar.gz"
            self.assertIn(marker, workflow)
            start = workflow.index(marker)
            command = workflow[start : workflow.index("\n\n", start)] if "\n\n" in workflow[start:] else workflow[start:]
            self.assertIn(
                "core",
                command,
                f"the {vendor} orchestrator archive does not ship the core package the adapter imports",
            )


class SchemaTest(unittest.TestCase):
    def access_values(self, schema: dict, capability: str) -> set[str]:
        """What the emitted schema permits for one capability's `access`.

        Handles both the current generic shape (one binding definition under
        additionalProperties) and a capability-specific one, so the test does not
        prescribe how the fix is written.
        """
        container = schema["$defs"]["source"]["properties"]["capabilities"]
        definition = container.get("properties", {}).get(capability, container.get("additionalProperties"))

        found: set[str] = set()

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "access" and isinstance(value, dict):
                        if "enum" in value:
                            found.update(value["enum"])
                        if "const" in value:
                            found.add(value["const"])
                    else:
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(definition)
        return found

    def test_the_schema_agrees_with_the_runtime_on_a_write_capability(self):
        """schemas.py:14-16 applies one generic binding to every capability, so the
        published schema accepts `post_inline_comment` with `access: "read"` while
        `validate_binding` rejects it. Setup or editor tooling validating against
        the shipped schema can therefore bless a document the hooks refuse.
        """
        with self.assertRaises(ContractError):
            validate_sources({
                "version": 2,
                "scm": {"capabilities": {"post_inline_comment": {
                    "kind": "mcp_tool", "server": "github", "tool": "post_comment",
                    "access": "read", "effect": "scm.comment.create",
                }}, "unsupported": []},
                "tracker": {"capabilities": {}, "unsupported": []},
            })
        self.assertNotIn(
            "read",
            self.access_values(sources_schema(), "post_inline_comment"),
            "the schema permits an access the runtime rejects",
        )


class CodexInstallerTest(unittest.TestCase):
    def managed(self) -> dict[str, bytes]:
        return CODEX_INSTALLER._load_sources(CODEX_INSTALLER._adapter_root())

    def test_a_previous_release_install_can_be_upgraded(self):
        """install_codex_adapter.py:137 — the back-compat default synthesizes
        {"agents/<name>": digest} from a legacy record, but expected_hashes now
        always carries the new skill entry too, so the dicts differ by
        construction and every existing managed install is refused as
        incompatible. The shim is dead code and the upgrade path is closed.
        """
        sources_map = self.managed()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "codex"
            for name, data in sources_map.items():
                target = base / name
                target.parent.mkdir(parents=True, exist_ok=True)
                # A previous-release install carries the agents but not the skill.
                if not name.startswith("agents/"):
                    continue
                target.write_bytes(data)

            record = Path(tmp) / "record.json"
            record.write_text(json.dumps({"agent_hashes": {
                name.removeprefix("agents/"): CODEX_INSTALLER._sha256(data)
                for name, data in sources_map.items() if name.startswith("agents/")
            }}), encoding="utf-8")

            config = Path(tmp) / "config.toml"
            config.write_text("[agents]\nmax_depth = 40\n", encoding="utf-8")

            try:
                CODEX_INSTALLER._preflight(base, config, record, sources_map)
            except ValueError as error:
                self.fail(f"a previous-release install could not be upgraded: {error}")

    def test_the_generated_config_is_parseable_with_an_awkward_path(self):
        """install_codex_adapter.py:107 interpolates a filesystem path straight
        into a TOML basic string. A backslash (Windows) or a quote makes
        config.toml unparseable."""
        import tomllib

        edit = CODEX_INSTALLER.plan_config_edit("", Path('/tmp/a "quoted"\\path/codex'))
        try:
            tomllib.loads(edit.after)
        except tomllib.TOMLDecodeError as error:
            self.fail(f"the installer emitted unparseable TOML: {error}")

    def test_the_hooks_do_not_match_every_tool_call(self):
        """install_codex_adapter.py:106,108 register matcher = ".*" on both
        PreToolUse and PostToolUse, so every Read, Edit and Grep in every Codex
        session spawns an interpreter that imports the core package, reads and
        revalidates sources.json, and globs the checkpoint directory — twice per
        tool call. The Claude installer deliberately narrows its matcher for this
        exact reason.
        """
        edit = CODEX_INSTALLER.plan_config_edit("", Path("/tmp/codex"))
        self.assertNotIn('matcher = ".*"', edit.after)


class HotPathTest(unittest.TestCase):
    def test_one_gated_call_validates_the_document_once(self):
        """mcrt_poster_guard_hook.py:125 — `evaluate` already resolved `sources`
        and `ids` before delegating, and `_evaluate_v2` recomputes both; then
        `binding_digest` validates the same normalized document a third time.
        Inside a synchronous PreToolUse hook with timeout = 5, this is the hot
        path.
        """
        calls = []
        real = contracts_module.validate_sources

        def counting(value):
            calls.append(value)
            return real(value)

        with tempfile.TemporaryDirectory() as tmp:
            root, _, _ = workspace_with(tmp, ["f1"])
            CLAUDE_HOOK.validate_sources = counting
            contracts_module.validate_sources = counting
            try:
                CLAUDE_HOOK.evaluate(
                    "mcp__github__post_comment",
                    {"body": "the issue [mcrt:f1] is real", "pull_request_id": "42"},
                    root,
                )
            finally:
                CLAUDE_HOOK.validate_sources = real
                contracts_module.validate_sources = real

        self.assertEqual(len(calls), 1, f"sources.json was validated {len(calls)} times for one tool call")


class _Stdin:
    """Minimal stdin stand-in; the hooks only ever call .read()."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


if __name__ == "__main__":
    unittest.main()
