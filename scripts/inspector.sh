#!/usr/bin/env bash
#
# MCP Inspector wrapper — Web UI or CLI for wire-protocol debugging (L1).
#
# Usage:
#   ./scripts/inspector.sh              # Web UI
#   ./scripts/inspector.sh cli tools/list
#   ./scripts/inspector.sh cli initialize --format json
#
# Requires Node.js >= 22 (MCP Inspector v2).
#

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SERVER="$ROOT/scripts/kosis-mcp-inspector.sh"

if [[ -f "$HOME/.nvm/nvm.sh" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.nvm/nvm.sh"
  nvm use 22 >/dev/null 2>&1 || true
fi

node_major="$(node -p "Number(process.versions.node.split('.')[0])")"
if [[ "$node_major" -lt 22 && -d "$HOME/.nvm/versions/node" ]]; then
  node22="$(ls -d "$HOME/.nvm/versions/node"/v22.* 2>/dev/null | sort -V | tail -1)"
  if [[ -n "$node22" ]]; then
    export PATH="$node22/bin:$PATH"
    node_major="$(node -p "Number(process.versions.node.split('.')[0])")"
  fi
fi
if [[ "$node_major" -lt 22 ]]; then
  echo "Node.js >= 22 required for MCP Inspector (current: $(node -v))" >&2
  exit 1
fi

INSPECTOR=(npx --yes @modelcontextprotocol/inspector@latest)

if [[ "${1:-}" == "cli" ]]; then
  shift
  METHOD="${1:-tools/list}"
  shift || true
  exec "${INSPECTOR[@]}" --cli "$SERVER" --method "$METHOD" "$@"
fi

exec "${INSPECTOR[@]}" "$SERVER"
