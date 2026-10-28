#!/usr/bin/env bash
# Pebble-local Claude Code: own install, HOME and config dir inside this repo.
# Auth: put CLAUDE_CODE_OAUTH_TOKEN (from `backend/scripts/claude.sh setup-token`) in Pebble/.env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUNTIME="$ROOT/.runtime"
TOKEN=""
if [[ -f "$ROOT/.env" ]]; then
  TOKEN="$(sed -n 's/^CLAUDE_CODE_OAUTH_TOKEN=//p' "$ROOT/.env" | tail -1)"
fi

mkdir -p "$RUNTIME/home" "$RUNTIME/claude-config"

exec env -i \
  PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  TERM="${TERM:-xterm-256color}" \
  LANG="${LANG:-en_US.UTF-8}" \
  HOME="$RUNTIME/home" \
  CLAUDE_CONFIG_DIR="$RUNTIME/claude-config" \
  ${TOKEN:+CLAUDE_CODE_OAUTH_TOKEN="$TOKEN"} \
  "$RUNTIME/claude/node_modules/.bin/claude" "$@"
