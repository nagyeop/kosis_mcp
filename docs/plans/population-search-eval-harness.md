# 인구 통계표 검색 — eval harness (구현 현황)

> **목적**: `population-search-backlog.md` 가설·실험을 Langfuse experiment로 재현 실행하고 run 비교·실패 분석까지 이어지게 한다.  
> **참조**: 골드 `tests/testset/gold_queries.json`, 지표 `docs/context/0_KOSIS 개선연구_평가지표 설명.html`, backlog `docs/plans/population-search-backlog.md`

---

## 1. 요약

L3 tool-direct eval harness는 **동작 가능한 상태**다. Dataset 업로드 → mode별 experiment → item score → Langfuse UI 비교까지 한 번에 돌릴 수 있다.

**평가 관점에서 L4 E2E는 별도 시스템이 아니라 `RunConfig.mode`에 mode 하나를 더하는 것**에 가깝다. dataset·upload·evaluator·Langfuse run 비교 흐름은 동일하고, `task`가 “tool 1회 직접 호출” 대신 “LLM agent + MCP multi-step”을 실행하는 것만 다르다.

| 구분 | 상태 |
|------|------|
| Harness 코드 (`scripts/eval/`, `src/kosis_mcp/eval/`) | ✅ |
| L2 단위 테스트 (`tests/eval/`, 17 tests) | ✅ |
| Dataset 3종 (gold / ops-gold / edge) 업로드 스크립트 | ✅ |
| L3 mode 3종 (`direct_search`, `direct_quick`, `direct_list`) | ✅ |
| Langfuse item evaluator (deterministic metrics) | ✅ (일부 지표 제외, §5) |
| AGENTS.md 실행 안내 | ✅ |
| **L4 mode (`e2e_agent`)** | ❌ 미착수 — §9 |
| Prod observation evaluator | ❌ 미착수 |

L3/L4 모두 **KOSIS_API_KEY + Langfuse 키 + 네트워크**가 필요(L4는 LLM API 키 추가). PR gate 아님, 수동 실행만.

---

## 2. CI 레벨과 mode 모델

| 레벨 | 위치 | 역할 |
|------|------|------|
| L1 Inspector | `scripts/ci.sh` | MCP wire protocol |
| L2 pytest | `tests/test_*.py`, `tests/eval/` | 순수 Python (metrics, outcome, testset schema) |
| **L3 eval** | `scripts/eval/` | tool-direct mode — KOSIS API + Langfuse experiment |
| **L4 eval** | `src/kosis_mcp/eval/agent.py` *(예정)* | `e2e_agent` mode — agent + MCP + 동일 experiment |

```
tests/testset/*.json
       │
       ▼
  upload_dataset.py  ──►  Langfuse Dataset
       │
       ▼
  run_experiment.py  ──►  dataset.run_experiment(task, item_evaluator)
       │
       ├─ mode=direct_*  ──► invoke_tool()        ──► normalize_outcome(single tool)
       │
       └─ mode=e2e_agent ──► run_agent()         ──► normalize_session(trace)
                                    │                      │
                                    └─ MCP client ◄────────┘
       │
       ▼
  @observe tool traces + item scores → Langfuse Dataset Run UI
```

**L3 vs L4 (eval harness 안에서의 차이만)**

| | L3 `direct_*` | L4 `e2e_agent` |
|---|---------------|----------------|
| task | `invoke_tool(mode, query)` | `run_agent(query, agent_config)` |
| tool 선택 | harness가 mode로 고정 | LLM이 prompt·description 보고 선택 |
| outcome 소스 | 단일 tool JSON | 세션 trace 전체 (tool call 순서 + tableId walk) |
| 재현성 | 높음 | model·prompt·temperature 고정 필요 |
| evaluators | 동일 `item_evaluator` (+ routing score 추가 가능) | 동일 |

---

## 3. 구현된 파일 (L3)

```
scripts/eval/
  upload_dataset.py    # testset JSON → Langfuse dataset (upsert by query_id)
  run_experiment.py    # CLI: --run-id, --mode, --dataset, --cache, --limit
  smoke_modes.py       # Q001 × 3 mode smoke (Langfuse 불필요)

src/kosis_mcp/eval/
  outcome.py           # tool JSON → ranked_table_ids, predicted_action
  metrics.py           # recall@k, mrr, ndcg, hn_violation, …
  evaluators.py        # Langfuse SDK item_evaluator
  runner.py            # RunConfig, invoke_tool, run_experiment

tests/eval/
  test_metrics.py
  test_outcome.py
  test_evaluators.py
  test_testset.py      # ops/edge JSON schema 검증
```

**Run config** (`runner.RunConfig`, L3):

- `run_id`, `mode` (`direct_search` | `direct_quick` | `direct_list` | `e2e_agent` *(예정)*)
- `cache`: `bypass`(기본, `EVAL_CACHE_BYPASS=1`) | `use`
- `limit`: 기본 10 (L3 direct_* 전용)

**Task (L3)**: tool impl 직접 import — stdio MCP subprocess 불필요.

---

## 4. Dataset

| Langfuse dataset | 소스 JSON | 건수 | 용도 |
|------------------|-----------|------|------|
| `population-search-gold-v1` | `gold_queries.json` | 50 | 전수 eval · run 비교 기준 |
| `population-search-ops-gold-v1` | `ops_gold_queries.json` | 30 | 운영 골드 subset |
| `population-search-edge-v1` | `edge_queries.json` | 132 | 엣지·회귀 |

업로드: `upload_dataset.py --dataset <name>`. idempotent key = `query_id`. JSON 수정 시 dataset 이름 bump(`v2`) 권장.

---

## 5. Evaluator (구현됨)

HTML 평가지표 ↔ Langfuse score name:

| Score | 조건 | 비고 |
|-------|------|------|
| `recall_at_5` | `expected_action==single_table` | ✅ |
| `top1` | single_table | ✅ |
| `mrr_at_10` | single_table | ✅ |
| `ndcg_at_10` | single_table | ✅ |
| `hn_violation` | `hard_negative_ids` 지정 item | ✅ |
| `multi_exact_set` | multi_table | ✅ |
| `multi_gold_recall` | multi_table | ✅ |
| `special_action` | clarify / exclude / no_exact_table | ✅ (한계 §6) |
| `overall_action` | 전체 | ✅ (한계 §6) |
| `candidate_recall_at_10` | single_table | ❌ **미구현** |

Run-level aggregate·slice(`query_group`)는 커스텀 `run_evaluator` 없이 **`result.format()` + Langfuse Dataset Run UI** metadata 필터로 본다.

---

## 6. 알려진 한계 (L3 Phase 1)

현재 tool은 `recommendedAction` / `action` 필드를 반환하지 않는다.

- `predicted_action`: 후보 empty → `no_exact_table`, 아니면 `single_table` 휴리스틱만
- clarify(5건)·multi_table(5건)의 `special_action` / `overall_action`은 **구조적으로 낮게 나올 수 있음** — over-interpret 금지
- `direct_list` mode는 item `query`를 **사용하지 않음** — 항상 `get_statistics_list(recommendedTopic="population")` 고정 호출 (§10 참고)

L4 `e2e_agent`에서는 query-aware이며, LLM이 search / quick / list / chain 등 **라우팅**을 스스로 고른다. clarify·exclude 판단도 agent outcome으로 평가 가능(§9).

HTML 연구 baseline(VDB→RRF→reranker)은 이 레포에서 실행·import하지 않음. MCP run끼리 Langfuse UI에서 비교.

---

## 7. 실행 (L3)

필요 env: `KOSIS_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, (`LANGFUSE_BASE_URL`)

```bash
# dataset 업로드 (최초 1회 · --dataset이 소스 JSON 선택)
PYTHONPATH=src .venv/bin/python scripts/eval/upload_dataset.py --dataset population-search-gold-v1
PYTHONPATH=src .venv/bin/python scripts/eval/upload_dataset.py --dataset population-search-ops-gold-v1
PYTHONPATH=src .venv/bin/python scripts/eval/upload_dataset.py --dataset population-search-edge-v1

# mode smoke (Langfuse 불필요, KOSIS_API_KEY만)
PYTHONPATH=src .venv/bin/python scripts/eval/smoke_modes.py

# MCP baseline experiment
PYTHONPATH=src .venv/bin/python scripts/eval/run_experiment.py \
  --run-id mcp-direct_search-2026-08-27 \
  --mode direct_search \
  --dataset population-search-gold-v1
```

출력: `result.format()` 요약 (평균 score, dataset run URL).

**실패 분석 workflow** (trace drill-down):

1. Dataset run에서 `recall_at_5=0` 또는 `hn_violation=1` item 필터
2. 해당 item trace → `search.merge` metadata, `kosis.openapi.request` span 확인
3. run description/metadata: `baseline_type=mcp mode=… cache=…`

---

## 8. 남은 작업 (L3 harness 보완)

| 작업 | 설명 |
|------|------|
| `candidate_recall_at_10` | evaluator + metric 추가 (후보 pool 넓을 때) |
| Task trace metadata | `query_id`, `query_group`를 trace metadata에 명시 (`update_current_trace`) — UI drill-down 편의 |
| **Prod observation evaluator** | `search_has_results`, `search_term_count` 등 Langfuse UI code evaluator |
| **LLM-as-judge** | clarify adequacy — L4 agent 이후 소량 calibration (선택) |

### 하지 않을 것 (의도)

- L3/L4 eval CI gate / GitHub workflow
- 커스텀 `run_evaluator` (slice JSON 등) — Langfuse UI에 위임
- HTML 연구 baseline import
- 운영셋 xlsx ~1,775 파이프 — ops-gold(30)·edge(132) dataset으로 대체

---

## 9. L4 `e2e_agent` mode — 설계·할 일

평가 harness 관점에서 L4는 **새 experiment 프레임워크가 아니라 mode 확장**이다.

```python
# 목표 RunConfig (runner.py 확장)
@dataclass(frozen=True)
class RunConfig:
    run_id: str
    mode: Literal[
        "direct_search", "direct_quick", "direct_list",
        "e2e_agent",          # ← L4
    ]
    cache: Literal["bypass", "use"] = "bypass"
    limit: int = 10
    # e2e_agent 전용
    model: str = ""           # e.g. "openai/gpt-4.1" — run마다 고정
    prompt_id: str = "statistics_assistant"
    max_steps: int = 8
    mcp_transport: Literal["stdio", "http"] = "stdio"
```

`run_experiment.py --mode e2e_agent` 한 줄로 L3와 같은 dataset·evaluator·Langfuse run UI를 쓴다. run metadata만 `baseline_type=e2e`로 구분.

### 9.1 필수 작업 — agent 모듈

L3 `invoke_tool` 옆에 **agent loop**를 추가한다. MCP subprocess/HTTP로 실제 wire를 타야 L4가 의미 있다 (tool impl 직접 import는 L3와 동일해져 routing eval 불가).

**추가 파일 (안)**

```
src/kosis_mcp/eval/
  agent.py              # run_agent(): LLM ↔ MCP tool-calling loop
  session_outcome.py    # trace/conversation → outcome dict (L3 outcome.py와 분리)

scripts/eval/
  smoke_e2e.py          # Q001 또는 O001 1건 smoke (Langfuse optional)
  run_experiment.py     # --mode e2e_agent 분기 (기존 CLI 확장)
```

**`run_agent` 책임**

1. MCP client 연결 (`kosis-mcp` stdio 또는 HTTP `/mcp`)
2. system/user prompt — `statistics_assistant` prompt 또는 동등 system prompt
3. LLM tool-calling loop (max_steps, timeout)
4. `@observe(name="population_search_e2e")` span — nested tool `@observe`와 연결
5. 종료 시 `normalize_session(...)` → L3와 **동일 outcome shape**:

```python
{
  "predicted_action": "single_table" | "clarify" | "no_exact_table" | ...,
  "ranked_table_ids": ["DT_…", …],   # 세션 전체 tool output walk
  "tool_path": ["search_statistics", "get_table_info", …],
}
```

**RunConfig / env (e2e 추가)**

- LLM API key (provider별 — run config에 model 고정)
- `KOSIS_API_KEY`, Langfuse keys (L3와 동일)
- `MCP_AUTH_TOKEN` (HTTP transport 시)

**Smoke 순서**

```bash
# 1) agent 1건 (Langfuse 불필요)
PYTHONPATH=src .venv/bin/python scripts/eval/smoke_e2e.py --query-id O029

# 2) ops-gold 전수 (Langfuse)
PYTHONPATH=src .venv/bin/python scripts/eval/run_experiment.py \
  --run-id e2e-agent-2026-08-27 \
  --mode e2e_agent \
  --dataset population-search-ops-gold-v1
```

`gold_queries.json`(50)은 E2E에도 그대로 쓸 수 있다. ops-gold는 **운영·clarify·gate slice**가 더 많아 L4 smoke → 전수 순서에 적합.

### 9.2 L4에서 재사용 vs 추가

| Component | L4 |
|----------|-----|
| `upload_dataset.py` | 재사용 |
| `item_evaluator` / `metrics.py` | 재사용 (outcome shape 동일 가정) |
| `normalize_outcome` (단일 tool) | **미사용** → `normalize_session` |
| routing evaluator | **추가 가능** — `tool_path` vs `expected_tool_path` (metadata) |
| LLM-as-judge (clarify 품질) | Phase 2 — deterministic `special_action` 먼저 |

### 9.3 L4 run 비교 (Langfuse UI)

같은 dataset에서:

- `mcp-direct_search-{date}` (L3) vs `e2e-agent-{date}` (L4)
- slice: `query_group` metadata 필터
- drill-down: parent trace → tool call 순서 → `search.merge` / shortcut span

실패 분류 (backlog §5): wrong tool (H-A4), shortcut on table-search (H-Q3, H-J3), multi-step verify 누락 (H-H2).

### 9.4 L4 구현 체크리스트

| 순 | 작업 | 필수 |
|----|------|------|
| 1 | `agent.py` + MCP client loop | ✅ |
| 2 | `session_outcome.py` — trace walk | ✅ |
| 3 | `RunConfig.mode=e2e_agent`, `run_experiment` 분기 | ✅ |
| 4 | `smoke_e2e.py` | ✅ |
| 5 | ops-gold-v1 전수 run + L3 baseline UI 비교 | |
| 6 | routing evaluator (`tool_path`) | 선택 |
| 7 | gold-v1(50) 전수 run | 선택 |
| 8 | LLM-as-judge clarify calibration | 선택 |

---

## 10. eval harness 밖 (backlog 제품 작업)

아래는 **harness TODO가 아니라** `population-search-backlog.md` 제품·tool 개선이다. 완료되면 eval 쪽은 metric 추가 없이 `predicted_action` 소스만 바뀐다.

### `direct_list`가 query를 안 쓰는 이유

`runner.invoke_tool`의 `direct_list`는 dataset item의 질의를 넘기지 않는다:

```python
await tool_get_statistics_list(recommendedTopic="population", limit=...)
```

즉 50건 전부 **동일한 인구 추천 카드**(`TOPIC_RECOMMENDATIONS["population"]`)를 받는다. “인구밀도 vs 출산율” 같은 질의별 list 성능을 재는 baseline이 **아니다** — `direct_search` / `direct_quick`가 query-aware baseline이다.

나중에 `get_statistics_list`가 query·검색어를 받도록 바뀌면, harness에서 `direct_list` 호출만 맞추면 되고 별도 “eval 재정의” 작업은 없다.

### Action surface (Phase 2)

골드의 `expected_action`은 `single_table` / `multi_table` / `clarify` / `no_exact_table` 네 가지인데, **현재 tool JSON에는 이 값이 없다**. harness는 후보 유무로만 추측한다:

- `ranked_table_ids` 비어 있음 → `no_exact_table`
- 아니면 → `single_table`

그래서 clarify 5건·multi 5건의 `special_action` / `overall_action` 점수는 **의미가 제한적**이다.

Phase 2 = backlog **제품 작업**: tool 응답에 `recommendedAction`(또는 `action`) 필드를 실제로 반환하게 하거나, `find_population_tables` / `resolve_population_query` 같은 통합 tool을 만드는 것 (H-J1, H-T1). L4 agent eval에서도 `normalize_session`이 tool action 필드를 읽으면 `special_action`이 의미를 갖는다.

---

## 부록 A: gold 50 — expected_action 분포

| expected_action | 건수 | Phase 1 eval |
|-----------------|------|--------------|
| single_table | 37 | recall/top1/mrr/ndcg/hn |
| multi_table | 5 | multi_* (action 휴리스틱 한계) |
| clarify | 5 | special_action *(tool action surface 없음)* |
| no_exact_table | 3 | special_action *(partial)* |

## 부록 B: ops_gold 30 — expected_action 분포 (현재)

| expected_action | 건수 | query_id |
|-----------------|------|----------|
| single_table | 18 | O001–O014, O016, O019–O021 |
| multi_table | 1 | O017 |
| clarify | 5 | O015, O022, O023, O024, O029 |
| no_exact_table | 4 | O018, O025, O026, O027 |
| exclude | 2 | O028, O030 |

---

*문서 버전: 2026-08-27 · L3 구현 완료 + L4 mode 확장 설계*
