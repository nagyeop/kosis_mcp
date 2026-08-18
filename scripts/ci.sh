#!/usr/bin/env bash
#
# CI entrypoint — L1 Inspector (wire protocol) then L2 pytest (business logic).
#
# L1: everything Inspector can verify over stdio JSON-RPC.
# L2: pure Python logic that Inspector cannot reach.
#

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi

"$VENV/bin/pip" install -q -e ".[dev]"

export KOSIS_API_KEY="${KOSIS_API_KEY:-test-key-for-unit-tests}"
export FASTMCP_SHOW_SERVER_BANNER=false

echo "=== L1: MCP Inspector (wire protocol) ==="

command -v npx >/dev/null || { echo "npx is required for L1 checks" >&2; exit 1; }

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
  echo "Node.js >= 22 required for MCP Inspector L1 (current: $(node -v))" >&2
  exit 1
fi

INSPECTOR=(npx --yes @modelcontextprotocol/inspector@latest)
SERVER="$ROOT/scripts/kosis-mcp-inspector.sh"
CLI=( "${INSPECTOR[@]}" --cli "$SERVER" --format json )

EXPECTED_TOOLS=(
  quick_stats
  quick_trend
  quick_rank
  explain_statistic
  search_statistics
  get_statistics_list
  get_statistics_data
  compare_statistics
  analyze_time_series
  get_table_info
  fetch_kosis_excel
  chain_region_brief
  chain_compare_regions
  chain_policy_indicator
)

inspector() {
  "${CLI[@]}" "$@"
}

assert_json() {
  local label="$1"
  local json="$2"
  local check="$3"
  "$VENV/bin/python" -c "
import json, sys
data = json.loads(sys.argv[1])
check = sys.argv[2]
if check == 'init':
    assert data['result']['serverInfo']['name']
elif check == 'tools':
    tools = data['result']['tools']
    names = {t['name'] for t in tools}
    expected = set(sys.argv[3:])
    assert len(names) == 14, names
    assert expected <= names, expected - names
    expected_ann = {
        'readOnlyHint': True,
        'destructiveHint': False,
        'idempotentHint': True,
        'openWorldHint': True,
    }
    for tool in tools:
        ann = tool.get('annotations') or {}
        for key, value in expected_ann.items():
            assert ann.get(key) == value, f\"{tool['name']}.{key}\"
    quick_stats = next(t for t in tools if t['name'] == 'quick_stats')
    schema = quick_stats['inputSchema']
    assert 'query' in schema['properties']
    assert 'query' in schema['required']
elif check == 'resources':
    uris = {r['uri'] for r in data['result']['resources']}
    assert 'kosis://categories/tree' in uris
    assert 'kosis://indicators/list' in uris
elif check == 'resource_read':
    contents = data['result']['contents']
    assert contents, 'empty contents'
    parsed = json.loads(contents[0]['text'])
    assert isinstance(parsed, (dict, list))
elif check == 'prompts':
    names = {p['name'] for p in data['result']['prompts']}
    assert 'statistics_assistant' in names
else:
    raise SystemExit(f'unknown check: {check}')
" "$json" "$check" "${@:4}" || { echo "L1 check failed: $label" >&2; exit 1; }
}

echo "L1: initialize"
init_out="$(inspector --method initialize)"
assert_json "initialize" "$init_out" init

echo "L1: tools/list"
tools_out="$(inspector --method tools/list)"
assert_json "tools/list" "$tools_out" tools "${EXPECTED_TOOLS[@]}"

echo "L1: resources/list"
resources_out="$(inspector --method resources/list)"
assert_json "resources/list" "$resources_out" resources

echo "L1: prompts/list"
prompts_out="$(inspector --method prompts/list)"
assert_json "prompts/list" "$prompts_out" prompts

echo "L1: resources/read (categories)"
categories_out="$(inspector --method resources/read --uri kosis://categories/tree)"
assert_json "resources/read categories" "$categories_out" resource_read

echo "L1: resources/read (indicators)"
indicators_out="$(inspector --method resources/read --uri kosis://indicators/list)"
assert_json "resources/read indicators" "$indicators_out" resource_read

echo "=== L2: pytest (business logic) ==="
"$VENV/bin/pytest"

echo "CI passed (L1 Inspector + L2 pytest)"
