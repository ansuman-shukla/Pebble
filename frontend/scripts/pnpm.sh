#!/usr/bin/env bash
# Pebble's pinned pnpm (installed by backend/scripts/setup.sh into .runtime/pnpm).
# Store, cache and state stay inside the repo; minimumReleaseAge lives in frontend/pnpm-workspace.yaml.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNTIME="$ROOT/.runtime"

exec env -u XDG_DATA_HOME -u XDG_CONFIG_HOME -u XDG_CACHE_HOME -u XDG_STATE_HOME \
  pnpm_config_store_dir="$RUNTIME/pnpm-store" \
  pnpm_config_cache_dir="$RUNTIME/pnpm-cache" \
  pnpm_config_state_dir="$RUNTIME/pnpm-state" \
  npm_config_store_dir="$RUNTIME/pnpm-store" \
  npm_config_cache_dir="$RUNTIME/pnpm-cache" \
  npm_config_state_dir="$RUNTIME/pnpm-state" \
  PLAYWRIGHT_BROWSERS_PATH="$RUNTIME/ms-playwright" \
  PATH="$RUNTIME/bin:$PATH" \
  "$RUNTIME/pnpm/node_modules/.bin/pnpm" "$@"
