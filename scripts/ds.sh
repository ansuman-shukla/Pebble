#!/usr/bin/env bash
# Pebble's private devin-switch: vendored copy, its own DS_HOME and HOME inside this repo.
# Never touches ~/.local/share/devin-switch, the installed `ds`, or ~/.config/devin.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="$ROOT/.runtime"
DS="$ROOT/vendor/devin-switch/.venv/bin/ds"
DEVIN_BIN="${DEVIN_BIN:-/Applications/Devin.app/Contents/Resources/app/extensions/windsurf/devin/bin/devin}"

mkdir -p "$RUNTIME/ds" "$RUNTIME/home"

exec env -i \
  PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
  TERM="${TERM:-xterm-256color}" \
  LANG="${LANG:-en_US.UTF-8}" \
  HOME="$RUNTIME/home" \
  DS_HOME="$RUNTIME/ds" \
  DS_BINARY="$DEVIN_BIN" \
  "$DS" "$@"
