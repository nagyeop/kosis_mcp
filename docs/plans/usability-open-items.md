# 미해결 사용성 과제 — Python v2.0 (TypeScript 리포트 잔여)

> 출처: [docs/USABILITY_IMPROVEMENT.md](../USABILITY_IMPROVEMENT.md) (2026-01-05 TypeScript 테스트)  
> 범위: **당시 미해결·부분 해결로 남은 항목만**. 새 이슈 발굴·자치구 라우팅·배포 작업은 포함하지 않음.

---

## 컨텍스트

| 항목 | 값 |
|------|-----|
| 코드베이스 | Python FastMCP v2.0 (`src/kosis_mcp/`) |
| 이미 해결됨 (본 plan 제외) | `get_table_info` 동적 메타, `quick_stats`+별칭 88개, chain 도구, 6h 캐시 |
| 검증 상태 | 정적 코드 분석 완료. **라이브 KOSIS 회귀 테스트 미실시** |

---

## 미해결 항목 요약

| ID | 원본 이슈 | 상태 | 우선순위 |
|----|----------|------|---------|
| U1 | `search_statistics` 검색 순위 | 미해결 (추정) | **P1** |
| U2 | `compare_statistics` 다중 지역 `objL1` | 미해결 (추정) | **P2** |
| U3 | `get_statistics_list(recommendedTopic="population")` | 부분 해결 | **P3** |
| U4 | 인기 검색어 → 고정 테이블 (`POPULAR_QUERIES`) | 부분 해결 | **P4** |

---

## U1 — `search_statistics` 결과 후처리 (P1)

### 원본 증상

`search_statistics`만 쓰는 탐색 경로에서 아래 검색어가 **핵심 통계표가 아닌 결과**를 상위에 반환 (TypeScript 당시 5/11 실패).

| 검색어 | 기대 | 당시 실제 |
|--------|------|----------|
| 한국 인구 / 총인구 / 인구수 / 주민등록인구 | 총인구·주민등록인구 | 부양비·노령화지수 |
| 집값 | 주택가격 | 귀촌의 이유 |
| 주택가격 | 주택가격 | 주택소유(주택수) ⚠️ |

### 현재 코드

- `src/kosis_mcp/tools/more_tools.py` — `search_statistics()` (약 489행)
- KOSIS API 결과를 dedupe만 하고 **우선순위 재정렬 없음**
- `src/kosis_mcp/utils/query_parser.py` — `parse_query` / `generate_search_terms`로 검색어 확장만

### 작업

1. 키워드→대표 `tableId` 맵 추가 (원본 제안 `PRIORITY_TABLES`):

```python
SEARCH_PRIORITY_TABLES: dict[str, list[str]] = {
    "인구": ["DT_1B040A3", "DT_1B04005", "DT_1IN1503"],
    "총인구": ["DT_1B040A3", "DT_1B04005"],
    "인구수": ["DT_1B040A3", "DT_1B04005"],
    "주민등록인구": ["DT_1IN1503", "DT_1B040A3"],
    "집값": ["DT_1YL21101"],
    "주택가격": ["DT_1YL21101"],
}
```

2. `search_statistics` 반환 직전: 매칭 키워드가 있으면 해당 `tableId` 행을 **results 앞쪽으로 이동** (KOSIS에 없는 ID는 무시).
3. 키워드 추출: `parse_query(query)["keywords"]` + 원문 query substring 매칭.

### 검증 (원본 11건)

`KOSIS_API_KEY` 설정 후 아래 쿼리로 `search_statistics` 호출 — **top1~3 `tableName`이 기대 분야인지** 수동·스크립트 확인:

```
한국 인구, 총인구, 인구수, 주민등록인구, 집값, 주택가격,
실업률, GDP, 물가, 출산율, 서울 실업률
```

성공 기준 (원본): 위 11건 중 실패했던 5건 + 주택가격 ⚠️ 1건이 개선.

### 참고

- `quick_stats` 경로는 `KEYWORD_ALIASES`로 **이미 우회됨**. 본 작업은 **탐색 전용 경로** 보완.

---

## U2 — `compare_statistics` 다중 지역 비교 (P2)

### 원본 증상

`objL1: "11+21"` (서울+부산) 형식 비교 실패. 에러 시 원인·형식 안내 없음.

```json
{
  "success": false,
  "compareType": "item",
  "items": [],
  "summary": "비교 중 오류가 발생했습니다."
}
```

### 현재 코드

- `src/kosis_mcp/tools/stats_query.py` — `compare_statistics()` (약 308행)
- `objL1`을 단일 코드로만 `client.get_statistics_data`에 전달
- `except` 블록: `insights: [str(error)]`만, **`usageHint` 없음**

### 작업 (택 1 — 구현 전 역할 정리)

**A. `objL1` `+` 파싱 지원**

- `"11+21"` → 코드 리스트로 split → 각 코드별 fetch → `compareType="item"` 결과 merge
- KOSIS가 `+` 결합 objL1을 지원하는지 **먼저 라이브 probe** (미확인)

**B. 실패 UX만 보강 (최소)**

- `success: false` 응답에 `error`, `usageHint` 추가:

```
다중 지역 비교:
  - chain_compare_regions: "서울이랑 부산 실업률" (자연어, 권장)
  - compare_statistics: get_table_info로 objL1 코드 확인 후 단일 코드만
```

**C. `chain_compare_regions`를 공식 경로로 문서화**

- 코드 변경 최소. `statistics_assistant` 프롬프트·도구 description에 다지역 비교는 chain 사용 명시.

### 검증 (원본)

1. `compare_statistics(..., compareType="item", objL1="11+21", ...)` — A 선택 시 성공 또는 B/C 선택 시 친절한 안내
2. 기존 단일 지역/시점 비교 회귀 없음

### 참고

- `src/kosis_mcp/tools/more_tools.py` — `chain_compare_regions`가 자연어 다지역 비교는 **이미 커버**. U2는 **저수준 compare 도구 UX** 잔여 과제.

---

## U3 — population 추천 통계 확장 (P3)

### 원본 증상

`get_recommended_statistics("population")` top 결과에 **기본 인구수 통계 부재** — 부양비·노령화지수 위주.

**기대 (원본)**:
1. 주민등록인구현황
2. 시도별 총인구
3. 인구동태건수
4. 합계출산율
5. 고령인구비율

### 현재 코드

- `src/kosis_mcp/tools/more_tools.py` — `TOPIC_RECOMMENDATIONS["population"]`
- 현재 2개만:

```python
{"ORG_ID": "101", "TBL_ID": "DT_1B040A3", "TBL_NM": "주민등록인구"},
{"ORG_ID": "101", "TBL_ID": "DT_1B81A17", "TBL_NM": "합계출산율"},
```

- 도구: `get_statistics_list(recommendedTopic="population")` (`server.py`)

### 작업

`TOPIC_RECOMMENDATIONS["population"]["tables"]` 확장 (원본 제안 반영, `quick_stats`와 tableId 정합성 확인):

```python
{"ORG_ID": "101", "TBL_ID": "DT_1B040A3", "TBL_NM": "행정구역(시군구)별 주민등록인구"},
{"ORG_ID": "101", "TBL_ID": "DT_1IN1503", "TBL_NM": "주민등록인구현황"},
{"ORG_ID": "101", "TBL_ID": "DT_1B8000H", "TBL_NM": "인구동태건수"},
{"ORG_ID": "101", "TBL_ID": "DT_1B81A17", "TBL_NM": "합계출산율"},
{"ORG_ID": "101", "TBL_ID": "DT_1BPA002", "TBL_NM": "주요인구지표"},
```

`limit` 기본값(5)과 맞출 것.

### 검증

```python
await get_statistics_list(recommendedTopic="population", limit=5)
# recommendations 5건, 1~2번째가 총인구·주민등록 계열
```

---

## U4 — 인기 검색어 고정 매핑 (P4)

### 원본 제안

TypeScript 리포트 「추가 개선 아이디어 #1」— 자주 쓰는 질의를 검색 전에 대표 테이블로 바로 연결.

```typescript
const POPULAR_QUERIES = {
  '실업률': { tableId: 'DT_1DA7102S', objL1: '0', objL2: '00', itemId: 'T80' },
  '출산율': { tableId: 'DT_1B8000H', objL1: '00', itemId: 'T12' },
  '인구':   { tableId: 'DT_1B040A3', objL1: '00', itemId: 'T20' },
};
```

### 현재 코드

- `quick_stats` — `QUICK_STATS_PARAMS` (92키워드)로 **유사 역할 이미 수행**
- `search_statistics` — **POPULAR_QUERIES 없음**
- `cache.py` — TTL 캐시만, 질의→테이블 shortcut 없음

### 작업

**옵션 A (권장, U1과 통합)**  
U1의 `SEARCH_PRIORITY_TABLES`만으로 충분하면 U4 별도 구현 생략.

**옵션 B**  
`search_statistics` 진입 시 `POPULAR_QUERIES` hit이면 results 맨 앞에 **synthetic 추천 행** 1건 삽입 + `note: "인기 검색어 추천"` .

### 검증

`search_statistics("실업률")` top1이 `DT_1DA7102S` 계열인지 (U1과 중복 검증 가능).

---

## 공통 — 라이브 회귀 테스트 (미착수)

원본 20건 중 **미해결 경로만** 재현하는 스크립트 추가 권장:

```
scripts/verify_usability_open_items.py   # 또는 pytest + @pytest.mark.integration
```

| 구분 | 케이스 | 대상 |
|------|--------|------|
| search | 원본 11 검색어 | U1 |
| compare | `objL1="11+21"` 1건 + 단일 비교 1건 회귀 | U2 |
| recommend | `recommendedTopic="population"` | U3 |

`KOSIS_API_KEY` 없으면 skip. CI에는 넣지 않거나 optional job.

---

## 파일 위치

| 영역 | 파일 |
|------|------|
| search_statistics | `src/kosis_mcp/tools/more_tools.py` |
| query 확장 | `src/kosis_mcp/utils/query_parser.py`, `data/_query_parser.json` |
| compare | `src/kosis_mcp/tools/stats_query.py` |
| 추천 토픽 | `src/kosis_mcp/tools/more_tools.py` (`TOPIC_RECOMMENDATIONS`) |
| quick_stats (우회 경로, 참고) | `src/kosis_mcp/tools/quick_stats.py`, `data/quick_stats_params.py` |
| 다지역 비교 (대안) | `src/kosis_mcp/tools/more_tools.py` (`chain_compare_regions`) |
| 원본 분석 | `docs/USABILITY_IMPROVEMENT.md` |

---

## 권장 작업 순서

```
U1 search_statistics 후처리
  → scripts/verify (search 11건)
U3 population 추천 확장 (독립, 소규모)
U2 compare UX (A/B/C 결정 후)
  → verify compare 2건
U4는 U1으로 흡수 가능하면 생략
```

---

## 시작 멘트 예시

```
docs/plans/usability-open-items.md 기준으로 U1부터.
search_statistics에 SEARCH_PRIORITY_TABLES 후처리 추가.
KOSIS_API_KEY로 원본 11개 검색어 top3 확인 후 pytest/integration 스크립트 추가.
```
