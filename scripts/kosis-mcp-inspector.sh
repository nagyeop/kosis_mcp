#!/usr/bin/env bash
# MCP Inspector stdio entry — Inspector does not forward parent env to spawned servers.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -z "${KOSIS_API_KEY:-}" && -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
export KOSIS_API_KEY="${KOSIS_API_KEY:-test-key-for-unit-tests}"
export FASTMCP_SHOW_SERVER_BANNER=false
if [[ -x "$ROOT/.venv/bin/kosis-mcp" ]]; then
  exec "$ROOT/.venv/bin/kosis-mcp" "$@"
fi
exec kosis-mcp "$@"
