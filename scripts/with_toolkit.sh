#!/usr/bin/env bash
# Run the agent-plugins-toolkit CLI against this repository.
#
# The toolkit's packages are not published to npm (@agent-plugins/cli and
# @agent-plugins/core both 404 on the registry and depend on each other with
# `workspace:*`). So we clone a pinned checkout, build it once, and cache it
# under .toolkit/ — which is gitignored.
#
#   scripts/with_toolkit.sh validate plugins/monolithic-code-review-toolkit
#   scripts/with_toolkit.sh inspect  plugins/monolithic-code-review-toolkit
#   scripts/with_toolkit.sh install  plugins/... --vendor claude --target DIR
#
# Env overrides:
#   TOOLKIT_REPO   git URL          (default: Monolith-INC/agent-plugins-toolkit)
#   TOOLKIT_REF    commit-ish       (default: the pin below)
#   TOOLKIT_DIR    checkout path    (default: <repo>/.toolkit)
#   TOOLKIT_REBUILD=1               force a rebuild even if dist/ exists

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Pinned so validation is reproducible. Bump deliberately, never automatically.
TOOLKIT_REPO="${TOOLKIT_REPO:-https://github.com/Monolith-INC/agent-plugins-toolkit.git}"
TOOLKIT_REF="${TOOLKIT_REF:-b75aaa5c627599f1fdb25caff154e9a22d2e2640}"
TOOLKIT_DIR="${TOOLKIT_DIR:-$ROOT/.toolkit}"

PNPM_VERSION="10.14.0"
CLI_ENTRY="$TOOLKIT_DIR/packages/cli/dist/index.js"

log() { printf '[with_toolkit] %s\n' "$*" >&2; }

require() {
  command -v "$1" >/dev/null 2>&1 || {
    log "required command not found: $1"
    exit 127
  }
}

pnpm_run() {
  # pnpm is not assumed to be on PATH; npx resolves the pinned version.
  if command -v pnpm >/dev/null 2>&1; then
    pnpm "$@"
  else
    npx --yes "pnpm@${PNPM_VERSION}" "$@"
  fi
}

fetch_toolkit() {
  if [ -d "$TOOLKIT_DIR/.git" ]; then
    local current
    current="$(git -C "$TOOLKIT_DIR" rev-parse HEAD 2>/dev/null || echo none)"
    [ "$current" = "$TOOLKIT_REF" ] && return 0
    log "toolkit pin changed ($current -> $TOOLKIT_REF); refetching"
    git -C "$TOOLKIT_DIR" fetch --quiet origin "$TOOLKIT_REF" 2>/dev/null ||
      git -C "$TOOLKIT_DIR" fetch --quiet origin
    git -C "$TOOLKIT_DIR" checkout --quiet --detach "$TOOLKIT_REF"
    rm -rf "$TOOLKIT_DIR/packages/cli/dist"
    return 0
  fi

  log "cloning toolkit at $TOOLKIT_REF"
  rm -rf "$TOOLKIT_DIR"
  git clone --quiet "$TOOLKIT_REPO" "$TOOLKIT_DIR"
  git -C "$TOOLKIT_DIR" checkout --quiet --detach "$TOOLKIT_REF"
}

build_toolkit() {
  if [ -f "$CLI_ENTRY" ] && [ "${TOOLKIT_REBUILD:-0}" != "1" ]; then
    return 0
  fi
  log "building toolkit (first run for this pin; this takes a minute)"
  (
    cd "$TOOLKIT_DIR"
    pnpm_run install --frozen-lockfile
    pnpm_run build
  )
  [ -f "$CLI_ENTRY" ] || {
    log "build finished but CLI entry is missing: $CLI_ENTRY"
    exit 1
  }
}

main() {
  require git
  require node

  fetch_toolkit
  build_toolkit

  exec node "$CLI_ENTRY" "$@"
}

main "$@"
