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
| `CACHE_TTL_HOURS` | 기본 6 |
| `PORT` | HTTP 포트 (기본 3000) |
| `RATE_LIMIT_RPM` | IP당 분당 요청 (기본 60) |
| `MCP_AUTH_TOKEN` | 설정 시 `/mcp` Bearer 인증 |
| `MCP_CORS_ORIGIN` | 기본 `*` |
| `ACCESS_LOG` | `1`이면 path만 요청 로그 (쿼리스트링 미기록) |

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
L2 (pytest): `test_extract_keyword.py`, `test_utils.py` — 순수 Python 로직만.

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
