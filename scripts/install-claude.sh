#!/usr/bin/env bash
# Install the Monolithic Code Review Toolkit Claude Code plugin from the latest GitHub release.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Monolith-INC/monolithic-code-review-toolkit/main/scripts/install-claude.sh | bash
#
# Installs the skills payload, and stages the companion adapters beside it so
# `review-setup` can wire them into a repository. Staging is not wiring: no
# repository is touched here, and the knowledge adapter's third-party dependencies
# are not installed. Both are per-repository decisions that need a human, and this
# script runs through a pipe where there is nobody to ask.
#
# Optional environment variables:
#   MCRT_VERSION              Pin a release (e.g. 0.5.0). Default: latest GitHub release.
#   MCRT_CLAUDE_SKILLS_DIR    Plugin location. Default: ~/.claude/skills/monolithic-code-review-toolkit
#   MCRT_CLAUDE_ADAPTER_DIR   Adapter staging root. Default: ~/.claude/mcrt
#   MCRT_ADAPTERS             Comma list of adapters to stage: orchestrator, knowledge,
#                             or none. Default: orchestrator,knowledge
#   MCRT_PYTHON               Interpreter recorded for the adapters. Default: first of
#                             python3.12, python3 found on PATH.
#
# Written for bash 3.2 — no arrays, no mapfile. macOS still ships 3.2, and
# `curl | bash` runs in whatever bash is first on PATH.

set -euo pipefail

readonly REPO="Monolith-INC/monolithic-code-review-toolkit"
readonly INSTALL_DIR="${MCRT_CLAUDE_SKILLS_DIR:-${HOME}/.claude/skills/monolithic-code-review-toolkit}"
readonly ADAPTER_HOME="${MCRT_CLAUDE_ADAPTER_DIR:-${HOME}/.claude/mcrt}"
readonly REQUESTED_VERSION="${MCRT_VERSION:-}"
readonly REQUESTED_ADAPTERS="${MCRT_ADAPTERS:-orchestrator,knowledge}"
readonly MANIFEST="${ADAPTER_HOME}/install.json"
readonly KNOWN_ADAPTERS="orchestrator knowledge"

# Per-adapter facts: which release asset carries it, where it sits inside that
# archive, and which entry point installs it into a repository.
adapter_asset_suffix() {
  case "$1" in
    orchestrator) echo "claude-review-orchestrator" ;;
    knowledge) echo "knowledge-adapter" ;;
    *) return 1 ;;
  esac
}

adapter_archive_path() {
  case "$1" in
    orchestrator) echo "adapters/claude" ;;
    knowledge) echo "adapters/knowledge" ;;
    *) return 1 ;;
  esac
}

adapter_installer() {
  case "$1" in
    orchestrator) echo "install_claude_adapter.py" ;;
    knowledge) echo "install_knowledge_adapter.py" ;;
    *) return 1 ;;
  esac
}

require_command() {
  local name="$1"
  command -v "$name" >/dev/null 2>&1 || {
    echo "error: '${name}' is required but was not found on PATH" >&2
    exit 1
  }
}

resolve_python() {
  if [[ -n "${MCRT_PYTHON:-}" ]]; then
    echo "${MCRT_PYTHON}"
    return 0
  fi
  local candidate
  for candidate in python3.12 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      echo "${candidate}"
      return 0
    fi
  done
  echo "python3.12"
}

resolve_version() {
  if [[ -n "${REQUESTED_VERSION}" ]]; then
    echo "${REQUESTED_VERSION#v}"
    return 0
  fi
  curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | python3 -c "import json, sys; print(json.load(sys.stdin)['tag_name'].lstrip('v'))"
}

# Validate MCRT_ADAPTERS in the main shell, not a subshell: an unknown name has
# to be able to stop the install. A typo would otherwise produce an install that
# looks complete and is missing the thing it was asked for.
validate_adapter_selection() {
  local name known matched
  [[ "${REQUESTED_ADAPTERS}" == "none" ]] && return 0
  for name in $(echo "${REQUESTED_ADAPTERS}" | tr ',' ' '); do
    matched=""
    for known in ${KNOWN_ADAPTERS}; do
      [[ "${name}" == "${known}" ]] && matched="yes"
    done
    [[ -n "${matched}" ]] || {
      echo "error: unknown adapter '${name}' in MCRT_ADAPTERS" >&2
      echo "       expected a comma list of: ${KNOWN_ADAPTERS// /, }, or none" >&2
      exit 1
    }
  done
}

# Echo the requested adapters once each, in a stable order.
selected_adapters() {
  local known name
  [[ "${REQUESTED_ADAPTERS}" == "none" ]] && return 0
  for known in ${KNOWN_ADAPTERS}; do
    for name in $(echo "${REQUESTED_ADAPTERS}" | tr ',' ' '); do
      if [[ "${name}" == "${known}" ]]; then
        echo "${known}"
        break
      fi
    done
  done
}

install_payload() {
  local version="$1" tmpdir="$2"
  local asset archive
  asset="monolithic-code-review-toolkit-${version}-claude.tar.gz"
  archive="${tmpdir}/${asset}"

  echo "→ Downloading ${asset}..."
  curl -fsSL "https://github.com/${REPO}/releases/download/v${version}/${asset}" -o "${archive}"

  echo "→ Installing plugin to ${INSTALL_DIR}..."
  rm -rf "${INSTALL_DIR}"
  mkdir -p "${INSTALL_DIR}"
  tar -xzf "${archive}" --strip-components=1 -C "${INSTALL_DIR}" payload
}

# Stage one adapter's sources. Returns 1 when the release carries no such asset,
# so an older pinned release degrades to "plugin installed, adapter unavailable"
# rather than failing an otherwise good install.
stage_adapter() {
  local name="$1" version="$2" tmpdir="$3"
  local asset archive source_path destination installer
  asset="monolithic-code-review-toolkit-${version}-$(adapter_asset_suffix "${name}").tar.gz"
  archive="${tmpdir}/${asset}"
  source_path="$(adapter_archive_path "${name}")"
  destination="${ADAPTER_HOME}/${source_path}"
  installer="$(adapter_installer "${name}")"

  echo "→ Downloading ${asset}..."
  if ! curl -fsSL "https://github.com/${REPO}/releases/download/v${version}/${asset}" -o "${archive}"; then
    echo "  warning: release v${version} ships no ${name} adapter; skipping it" >&2
    return 1
  fi

  echo "→ Staging ${name} adapter in ${destination}..."
  rm -rf "${destination}"
  mkdir -p "${ADAPTER_HOME}"
  # Extract the archive whole rather than plucking out the adapter directory.
  # An orchestrator archive also carries `core/`, and the adapter resolves it as
  # `parents[2]/core` — two levels above its own file — so the archive's own
  # layout is already the correct staged layout.
  tar -xzf "${archive}" -C "${ADAPTER_HOME}"

  [[ -f "${destination}/${installer}" ]] || {
    echo "error: staged ${name} adapter has no ${installer}" >&2
    exit 1
  }

  # Fail closed on a missing shared runtime. An adapter that imports `core` and
  # cannot find it raises at import time; for the poster guard that means the
  # PreToolUse hook exits non-zero, which the host treats as a non-blocking hook
  # error — every guarded pull-request write would then be permitted. A staged
  # install that silently disables the approval gate is worse than no install.
  if grep -rqs -e "^from core\." -e "^import core" "${destination}"; then
    [[ -d "${ADAPTER_HOME}/core/review_harness" ]] || {
      echo "error: the ${name} adapter imports 'core' but the archive staged no core/;" >&2
      echo "       refusing to leave a guard that cannot load and would fail open" >&2
      exit 1
    }
  fi
}

# The manifest is the contract `review-setup` reads to offer per-repository
# wiring. Written through python so paths containing quotes or spaces stay valid
# JSON, and so the shape stays one definition rather than hand-built strings.
write_manifest() {
  local version="$1" python_bin="$2" staged="$3"
  mkdir -p "${ADAPTER_HOME}"
  MCRT_MANIFEST_VERSION="${version}" \
  MCRT_MANIFEST_PYTHON="${python_bin}" \
  MCRT_MANIFEST_PLUGIN_ROOT="${INSTALL_DIR}" \
  MCRT_MANIFEST_ADAPTER_HOME="${ADAPTER_HOME}" \
  MCRT_MANIFEST_STAGED="${staged}" \
  python3 - "${MANIFEST}" <<'PYTHON'
import json
import os
import sys

ADAPTERS = {
    "orchestrator": ("adapters/claude", "install_claude_adapter.py", False),
    "knowledge": ("adapters/knowledge", "install_knowledge_adapter.py", True),
}

home = os.environ["MCRT_MANIFEST_ADAPTER_HOME"]
staged = {}
for name in os.environ["MCRT_MANIFEST_STAGED"].split():
    relative, installer, requires_pip = ADAPTERS[name]
    root = os.path.join(home, relative)
    staged[name] = {
        "root": root,
        "installer": os.path.join(root, installer),
        "scope": "project",
        "requires_pip": requires_pip,
    }

manifest = {
    "schema_version": 1,
    "host": "claude",
    "version": os.environ["MCRT_MANIFEST_VERSION"],
    "plugin_root": os.environ["MCRT_MANIFEST_PLUGIN_ROOT"],
    "python": os.environ["MCRT_MANIFEST_PYTHON"],
    "adapters": staged,
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PYTHON
}

verify_install() {
  local manifest="${INSTALL_DIR}/.claude-plugin/plugin.json"
  local skills_root="${INSTALL_DIR}/skills"

  [[ -f "${manifest}" ]] || {
    echo "error: missing ${manifest} after install" >&2
    exit 1
  }

  local skill_count
  skill_count="$(find "${skills_root}" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')"
  [[ "${skill_count}" -ge 1 ]] || {
    echo "error: no skills found under ${skills_root}" >&2
    exit 1
  }

  echo "${skill_count}"
}

main() {
  require_command curl
  require_command tar
  require_command python3

  validate_adapter_selection

  local version python_bin tmpdir staged name skill_count
  version="$(resolve_version)"
  python_bin="$(resolve_python)"

  tmpdir="$(mktemp -d)"
  trap "rm -rf '${tmpdir}'" EXIT

  install_payload "${version}" "${tmpdir}"

  staged=""
  for name in $(selected_adapters); do
    if stage_adapter "${name}" "${version}" "${tmpdir}"; then
      staged="${staged}${staged:+ }${name}"
    fi
  done

  write_manifest "${version}" "${python_bin}" "${staged}"
  skill_count="$(verify_install)"

  cat <<EOF

✓ Installed monolithic-code-review-toolkit ${version} for Claude Code
  Plugin:   ${INSTALL_DIR}
  Skills:   ${skill_count} (full release payload)
  Adapters: ${staged:-none staged}
  Manifest: ${MANIFEST}

Next step: restart Claude Code, or run /reload-plugins.

Then run review-setup once in each repository you review. It records where
requirements and pull requests live, and offers to wire the staged adapters into
that repository — the review orchestrator with the provider tools it just
detected, and the knowledge MCP server against the store root you chose.
EOF
}

main "$@"
