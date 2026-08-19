#!/usr/bin/env bash
#
# KOSIS MCP — 로컬 stdio 등록 (macOS / Linux)
#
# Claude Desktop / Cursor 설정에 kosis-mcp (stdio)를 등록합니다.
# 사전: KOSIS_API_KEY, 그리고 `pip install kosis-mcp` 또는 이 레포 `pip install -e .`
#
# 사용:
#   KOSIS_API_KEY=... bash install.sh --client cursor
#

set -euo pipefail

SERVER_NAME="kosis-mcp"
CLIENT="all"
COMMAND="kosis-mcp"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client) CLIENT="$2"; shift 2 ;;
    --command) COMMAND="$2"; shift 2 ;;
    -h|--help)
      cat <<EOF
KOSIS MCP 로컬 설치

옵션:
  --client {claude|cursor|all}   설치할 클라이언트 (기본: all)
  --command <cmd>                실행 커맨드 (기본: kosis-mcp)
EOF
      exit 0
      ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "${KOSIS_API_KEY:-}" ]]; then
  echo "KOSIS_API_KEY 환경변수가 필요합니다." >&2
  exit 1
fi

python3 - <<PY
import json, os, pathlib, sys
client = "$CLIENT"
cmd = "$COMMAND"
name = "$SERVER_NAME"
key = os.environ["KOSIS_API_KEY"]
entry = {
  "command": cmd,
  "args": [],
  "env": {"KOSIS_API_KEY": key},
}
homes = {
  "claude": pathlib.Path.home() / "Library/Application Support/Claude/claude_desktop_config.json",
  "cursor": pathlib.Path.home() / ".cursor/mcp.json",
}
# Linux Claude path fallback
if sys.platform.startswith("linux"):
  homes["claude"] = pathlib.Path.home() / ".config/Claude/claude_desktop_config.json"

targets = list(homes.keys()) if client == "all" else [client]
for t in targets:
  path = homes[t]
  path.parent.mkdir(parents=True, exist_ok=True)
  data = {}
  if path.exists():
    try:
      data = json.loads(path.read_text())
    except Exception:
      data = {}
  servers = data.setdefault("mcpServers", {})
  servers[name] = entry
  path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
  print(f"updated {path}")
PY

echo "완료. 클라이언트를 재시작하세요."
