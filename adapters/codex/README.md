# Codex review-orchestrator adapter

This companion adapter adds isolated Codex custom agents around the portable
Monolithic Code Review Toolkit skills. It is intentionally outside
`plugins/monolithic-code-review-toolkit/`: the portable payload contract ships
only `SKILL.md` files and cannot carry custom agents or deterministic helpers.
It requires Python 3.12+ for its installer and deterministic guard utility.

## Install

Install the plugin using the normal marketplace or release-payload method first.
Then install this adapter into the trusted Codex scope you chose:

```bash
python3.12 adapters/codex/install_codex_adapter.py --scope project --project /path/to/repository
python3.12 adapters/codex/install_codex_adapter.py --scope user
```

Use `--dry-run` to inspect the exact target. The installer refuses to overwrite
unmanaged agents, records hashes for its own files, sets `agents.max_depth` to
at least two with a surgical TOML edit, and restores only its own change during
uninstall:

```bash
python3.12 adapters/codex/install_codex_adapter.py --scope project --project /path/to/repository --uninstall
```

Restart Codex after installation. This release documents the adapter only; it
does not install it into any consumer repository.

Tagged releases include `monolithic-code-review-toolkit-<version>-codex-review-orchestrator.tar.gz`.
After extracting it, run the same command from the extracted `adapters/codex/`
directory. The adapter archive is separate because portable plugin payloads
cannot include custom-agent TOML files or helper scripts.

## Review input

The root session delegates a JSON-equivalent input to `mcrt_review_orchestrator`:

```json
{
  "workspace": "/absolute/path/to/repository",
  "review_type": "story-postflight",
  "pull_request_id": "123",
  "lenses": ["all"],
  "decision": "hold",
  "quota_signal": {"kind": "remaining", "percent": 75}
}
```

`review_type` is one of `task`, `story-preflight`, `story-postflight`,
`feature`, `pr-preparation`, or `pr-comment-triage`. `decision: "post"`
requires explicit `approved_finding_ids`; `hold` never invokes the posting
agent. Code fixes remain outside this adapter and require a separate explicit
workflow.

## Safety and routing

- The root session owns all user interaction and approval decisions.
- The orchestrator sequences workers and checkpoints but never reviews source
  or writes external comments.
- Discovery is Luna/medium and runs only for unresolved setup or bounded diff
  inventory. Lifecycle validation is Terra/medium. One independent Sol/high
  challenge pass evaluates only verified candidates. Posting is Terra/medium.
- Every worker runs sequentially and returns a compact phase result. Runtime
  checkpoints live at `.monolithic-code-review/orchestrator/` in the reviewed
  workspace, never in this adapter checkout.
- An authoritative seven-day quota reading with remaining `<= 50`, used `>= 50`,
  or an ambiguous representation pauses the run. A cheaper model is never a
  bypass.
- The poster rechecks approval, evidence, SCM capability, and changed-line
  anchoring immediately before writing. It cannot approve PRs, resolve/reply to
  threads, edit source, commit, or create tracker writes.

Azure DevOps, GitHub, and other providers work only when `review-setup` has
recorded their real SCM and requirement capabilities in
`.monolithic-code-review/sources.json`.

## Deterministic utilities

`mcrt_review_guards.py` validates input and worker results, resolves the
lifecycle skill, tracks a single active checkpoint, reconciles approved finding
IDs, and evaluates only explicit quota signals. It never performs semantic code
review or contacts a provider.

An OpenAI Agents SDK service is intentionally not part of v1. If a later
centralized service needs API execution, traces, or dataset-based evaluations,
it may reuse this input/output/checkpoint contract rather than replacing the
portable review skills.
