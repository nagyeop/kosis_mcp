# AGENTS.md

## 실행

- **stdio (로컬 MCP)**: `KOSIS_API_KEY=... kosis-mcp` 또는 `python -m kosis_mcp`
- **HTTP**: `KOSIS_API_KEY=... kosis-mcp --http --port 3000`
- 개발: `python -m venv .venv && .venv/bin/pip install -e ".[dev]"`

## 환경변수

| 변수 | 역할 |
|------|------|
| `KOSIS_API_KEY` | 필수 — https://kosis.kr/openapi/ |
| `REDIS_URL` | 설정 시 Redis 캐시 (compose 기본 `redis://redis:6379/0`). 미설정이면 메모리 |
| `CACHE_TTL_HOURS` | 데이터 캐시 TTL(기본 6, 검색은 최대 1시간) |
| `KOSIS_RPM` | KOSIS 분당 호출 상한(기본 180, 키 한도 200) |
| `PORT` | HTTP 포트 (기본 3000) |
| `RATE_LIMIT_RPM` | IP당 분당 요청 (기본 60) |
| `MCP_AUTH_TOKEN` | 설정 시 `/mcp` Bearer 인증 |
| `MCP_CORS_ORIGIN` | 기본 `*` |
| `ACCESS_LOG` | `1`이면 path만 요청 로그 (쿼리스트링 미기록) |
| `LANGFUSE_PUBLIC_KEY` | Langfuse tracing (미설정 시 observe no-op) |
| `LANGFUSE_SECRET_KEY` | Langfuse tracing |
| `LANGFUSE_BASE_URL` | Langfuse 호스트 (예: `https://langfuse.clabi.kr`) |
| `LANGFUSE_TRACING_ENVIRONMENT` | trace environment tag (기본 `dev`) |

## Langfuse tracing

MCP tool 호출마다 Langfuse trace가 생성됩니다. `as_type="tool"` observe는 `server.py`의 `@mcp.tool` 래퍼에만 두고, HTTP는 `kosis.openapi.request`. FastMCP OTEL span(`scope: fastmcp`)은 `server.py` lifespan에서 export 제외. UI: `LANGFUSE_BASE_URL`/project/traces.

## 테스트

L1 Inspector = stdio subprocess + JSON-RPC wire. Inspector로 할 수 있는 것은 전부 L1.
L2 pytest = Inspector로 검증 불가한 비즈니스 로직 (키워드 추출, 파싱, 캐시, concurrency 등).

```bash
bash scripts/ci.sh          # L1 Inspector → L2 pytest (Node.js >= 22)
bash scripts/inspector.sh   # Web UI (수동 wire 디버깅)
.venv/bin/pytest            # L2 only

# Inspector 직접 호출 (래퍼 없이)
npx @modelcontextprotocol/inspector --cli .venv/bin/kosis-mcp --method tools/list
```

L1 (`scripts/ci.sh`): initialize, tools/list(14개·annotation·schema), resources/list·read, prompts/list.
L2 (pytest): `tests/test_*.py`(키워드 추출·검색어·find·series·키워드 계층·캐시/제한기), `tests/eval/` — KOSIS는 mock.
L3 eval (수동): 골드/ops/edge + KOSIS API + Langfuse experiment. PR gate 아님.

| Dataset | 소스 | 건수 |
|---------|------|------|
| `population-search-gold-v2` | `gold_queries.json` | 50 |
| `population-search-ops-gold-v2` | `ops_gold_queries.json` | 28 |
| `population-search-edge-v2` | `edge_queries.json` | 110 |

v2: 항목마다 `scope_category`(검색 범위, runner가 find_tables·browse_statistics `category`로 전달 — browse 지표는 분야 단위). exclude 24건은 `routing_excluded_queries.json`으로 분리.

```bash
# dataset 업로드 (최초 1회 · --dataset이 소스 JSON을 고름)
PYTHONPATH=src .venv/bin/python scripts/eval/upload_dataset.py --dataset population-search-gold-v2
PYTHONPATH=src .venv/bin/python scripts/eval/upload_dataset.py --dataset population-search-ops-gold-v2
PYTHONPATH=src .venv/bin/python scripts/eval/upload_dataset.py --dataset population-search-edge-v2

# tool smoke (Q001 × find_tables / quick_stats / browse_statistics)
PYTHONPATH=src .venv/bin/python scripts/eval/smoke_modes.py

# MCP baseline — --tool find_tables | quick_stats | browse_statistics
PYTHONPATH=src .venv/bin/python scripts/eval/run_experiment.py \
  --run-id mcp-find_tables-YYYY-MM-DD \
  --tool find_tables \
  --dataset population-search-gold-v2
```

필요 env: `KOSIS_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`.  
HTML 연구 baseline(VDB·reranker)은 이 harness에서 실행·import하지 않음 — MCP run끼리 Langfuse UI에서 비교.

## 배포 (Docker Compose)

```bash
cp .env.example .env   # KOSIS_API_KEY 설정
docker compose up -d --build
```

서비스: `mcp` (HTTP :3000) + `redis`. Redis는 내부 네트워크만.

## 배포 (Vercel)

```bash
npx vercel login
npx vercel env add KOSIS_API_KEY
npx vercel env add MCP_AUTH_TOKEN   # 권장
npx vercel --prod
```

엔트리포인트: `app.py` → Streamable HTTP `/mcp`. `REDIS_URL` 미설정 시 인메모리 캐시.
