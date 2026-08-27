#!/usr/bin/env bash
# Install the Monolithic Code Review Toolkit Cursor plugin from the latest GitHub release.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Monolith-INC/monolithic-code-review-toolkit/main/scripts/install-cursor.sh | bash
#
# Optional environment variables:
#   MCRT_VERSION          Pin a release (e.g. 0.2.2). Default: latest GitHub release.
#   MCRT_CURSOR_PLUGIN_DIR  Install location. Default: ~/.cursor/plugins/local/monolithic-code-review-toolkit

set -euo pipefail

readonly REPO="Monolith-INC/monolithic-code-review-toolkit"
readonly INSTALL_DIR="${MCRT_CURSOR_PLUGIN_DIR:-${HOME}/.cursor/plugins/local/monolithic-code-review-toolkit}"
readonly REQUESTED_VERSION="${MCRT_VERSION:-}"

require_command() {
  local name="$1"
  command -v "$name" >/dev/null 2>&1 || {
    echo "error: '${name}' is required but was not found on PATH" >&2
    exit 1
  }
}

resolve_version() {
  if [[ -n "${REQUESTED_VERSION}" ]]; then
    echo "${REQUESTED_VERSION#v}"
    return 0
  fi
  require_command curl
  require_command python3
  curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
    | python3 -c "import json, sys; print(json.load(sys.stdin)['tag_name'].lstrip('v'))"
}

verify_install() {
  local manifest="${INSTALL_DIR}/.cursor-plugin/plugin.json"
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

  local version asset url tmpdir archive
  version="$(resolve_version)"
  asset="monolithic-code-review-toolkit-${version}-cursor.tar.gz"
  url="https://github.com/${REPO}/releases/download/v${version}/${asset}"

  tmpdir="$(mktemp -d)"
  trap "rm -rf '${tmpdir}'" EXIT
  archive="${tmpdir}/${asset}"

  echo "→ Downloading ${asset}..."
  curl -fsSL "${url}" -o "${archive}"

  echo "→ Installing to ${INSTALL_DIR}..."
  rm -rf "${INSTALL_DIR}"
  mkdir -p "${INSTALL_DIR}"
  tar -xzf "${archive}" --strip-components=1 -C "${INSTALL_DIR}" payload

  local skill_count
  skill_count="$(verify_install)"

  cat <<EOF

✓ Installed monolithic-code-review-toolkit ${version} for Cursor
  Location: ${INSTALL_DIR}
  Skills:   ${skill_count} (full release payload)

Next step: reload Cursor (Developer → Reload Window), open Customize, and confirm
monolithic-code-review-toolkit is enabled.

Then run review-setup once in each repository you review.
EOF
}

main "$@"
