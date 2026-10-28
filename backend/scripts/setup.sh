#!/usr/bin/env bash
# One-time local setup. Everything lands inside this repo (vendor/ and .runtime/, both gitignored).
#   1. Pebble's private devin-switch at a pinned commit (+ its venv)
#   2. Pebble's private Claude Code at a pinned version
#   3. Pebble's pinned pnpm (frontend/scripts/pnpm.sh runs it; .runtime/bin/pnpm makes nested `pnpm` calls use it)
# Logins are separate steps: backend/scripts/import_ds_accounts.py, backend/scripts/claude.sh setup-token.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNTIME="$ROOT/.runtime"
DS_REPO="https://github.com/ansuman-shukla/devin-switch.git"
DS_COMMIT="d56b1a6"
CLAUDE_CODE_VERSION="2.1.305"
PNPM_VERSION="12.14.0"
CLEAN_ENV=(env -u XDG_DATA_HOME -u XDG_CONFIG_HOME -u XDG_CACHE_HOME -u XDG_STATE_HOME -u CHISEL_SESSION_DB
  -u DS_HOME -u DS_BINARY -u DS_RUN_ID -u DS_ACP_RUN_ID HOME="$RUNTIME/home")

mkdir -p "$RUNTIME/home"

if [[ ! -d "$ROOT/vendor/devin-switch/.git" ]]; then
  git clone -q "$DS_REPO" "$ROOT/vendor/devin-switch"
fi
git -C "$ROOT/vendor/devin-switch" fetch -q origin
git -C "$ROOT/vendor/devin-switch" checkout -q "$DS_COMMIT"
"${CLEAN_ENV[@]}" UV_CACHE_DIR="$RUNTIME/uv-cache" UV_PYTHON_INSTALL_DIR="$RUNTIME/uv-python" \
  uv sync -q --project "$ROOT/vendor/devin-switch" --frozen

"${CLEAN_ENV[@]}" npm install -s --prefix "$RUNTIME/claude" --cache "$RUNTIME/npm-cache" --no-fund --no-audit \
  "@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION"

"${CLEAN_ENV[@]}" npm install -s --prefix "$RUNTIME/pnpm" --cache "$RUNTIME/npm-cache" --no-fund --no-audit \
  "pnpm@$PNPM_VERSION"
mkdir -p "$RUNTIME/bin"
ln -sf ../../frontend/scripts/pnpm.sh "$RUNTIME/bin/pnpm"

# Spare folder of ds acp: its own git root so Devin rule discovery never climbs into Pebble.
[[ -d "$RUNTIME/home/.git" ]] || git init -q "$RUNTIME/home"

echo "setup done: devin-switch @ $DS_COMMIT, claude-code $CLAUDE_CODE_VERSION, pnpm $PNPM_VERSION"
