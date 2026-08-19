# KOSIS MCP 사용성 개선 리포트

> **원본**: 2026-01-05, TypeScript MCP 기준 자연어 사용성 테스트  
> **Python v2.0 검증**: 2026-08-19 — 코드·테스트 정적 분석 (KOSIS API 라이브 호출 **미실시**, `KOSIS_API_KEY` 없음)

TypeScript 시절의 정성적 분석이지만, **도구별 UX 문제는 FastMCP 포팅 후에도 그대로 남을 수 있습니다.**  
아래 「Python v2.0 검증 상태」표를 먼저 보고, 원본 이슈 설명은 참고용으로 유지합니다.

---

## Python v2.0 검증 상태 (2026-08-19)

| # | 원본 이슈 | 검증 방법 | 상태 | 비고 |
|---|----------|----------|------|------|
| 1 | `search_statistics` — 「인구」「집값」 검색 시 핵심 통계가 상위에 안 나옴 | `more_tools.py:search_statistics` 정적 분석 | **미해결 (추정)** | KOSIS 결과를 그대로 반환. `PRIORITY_TABLES`·재정렬 로직 없음. `parse_query`/`generate_search_terms`로 검색어 확장만 함 |
| 2 | `get_table_info` — usageHint 지역코드 하드코딩 | `get_table_info.py` + `meta_lookup.summarize_table_meta` | **해결됨** | 메타 API에서 동적 추출. 하드코딩된 「00=전국, 11=서울…」 예시 없음 |
| 3 | 추천 통계 — population 토픽에 핵심 인구표 누락 | `more_tools.py:TOPIC_RECOMMENDATIONS` | **부분 해결** | `DT_1B040A3`(주민등록인구), `DT_1B81A17`(합계출산율) 2개만. 원본이 기대한 `DT_1IN1503`·`DT_1B8000H` 등은 미포함 |
| 4 | `compare_statistics` — `objL1: "11+21"` 다중 지역 비교 실패 | `stats_query.py:compare_statistics` | **미해결 (추정)** | `+` 구분 파싱·다중 objL1 처리 없음. 실패 시 `insights: [str(error)]`만 반환, usageHint 가이드 없음 |
| 5 | LLM 5~6단계 플로우 — 간단 질문에 도구 연속 호출 | `quick_stats`·chain 도구 존재 확인 | **우회 해결** | `quick_stats`/`quick_trend`/`chain_*`로 원스텝 가능. **단, AI가 여전히 search→table_info→data 경로를 택하면 동일 통증 재발** |
| 6 | 동의어·별칭 (`집값`, `총인구`, `주민등록인구` 등) | `quick_stats_params.py:KEYWORD_ALIASES` | **해결됨 (quick_stats 한정)** | 88+ 별칭. `집값`→`주택가격`, `주민등록인구`→`인구` 등 |
| 7 | 인기 질의 캐싱·스마트 기본값 | `cache.py` + `quick_stats` 기본값 | **부분 해결** | 6시간 캐시·연도 미지정 시 최근값 등은 있음. 검색어→고정 테이블 `POPULAR_QUERIES` 맵은 없음 |

### 검증 한계

- **라이브 KOSIS 호출 없음** — #1, #4는 코드상 미구현이 확인됐지만, 실제 API 응답 순위·`11+21` 동작은 재현 테스트 필요
- **pytest 22건** — 키워드 추출·MCP 메타데이터 위주. `search_statistics` 순위·`compare_statistics` 다중 지역·추천 토픽 품질 **미검증**
- **미해결 과제 plan** — [docs/plans/usability-open-items.md](plans/usability-open-items.md) (U1~U4, TypeScript 리포트 잔여만)

### 우선순위 (현재 코드 기준, 미착수)

| 우선순위 | 항목 | 근거 |
|---------|------|------|
| P1 | `search_statistics` 결과 후처리 (키워드별 대표 테이블 상위 고정) | `quick_stats`를 쓰지 않는 탐색 경로에서 원본 #1 그대로 |
| P2 | `compare_statistics` 다중 지역 UX — `regionName` 복수 입력 또는 `objL1` `+` 파싱 + 실패 시 usageHint | 원본 #4 + `chain_compare_regions`와 역할 중복 정리 필요 |
| P3 | `TOPIC_RECOMMENDATIONS` population 확장 | 원본 #3 — 2개→5개 수준 |
| — | 라이브 회귀 테스트 스크립트 | `KOSIS_API_KEY`로 원본 11개 검색어 + compare 2건 재현 |

---

## 원본 테스트 개요 (2026-01-05, TypeScript)

**테스트 관점**: 일반인/LLM이 처음 MCP를 사용할 때  
**테스트 방법**: 자연스러운 질문으로 전체 플로우 테스트

---

## 발견된 주요 문제점 (원본)

### 1. search_statistics - 자연어 검색 실패

| 검색어 | 기대 결과 | 실제 결과 (당시) | 상태 |
|--------|----------|-----------------|------|
| "한국 인구" | 총인구/인구수 통계 | 부양비 및 노령화지수 | ❌ |
| "총인구" | 인구수 통계 | 부양비 및 노령화지수 | ❌ |
| "인구수" | 인구수 통계 | 부양비 및 노령화지수 | ❌ |
| "주민등록인구" | 주민등록인구 | 부양비 및 노령화지수 | ❌ |
| "집값" | 주택가격 통계 | 귀촌의 이유 | ❌ |
| "주택가격" | 주택가격 통계 | 주택소유통계(주택수) | ⚠️ |
| "실업률" | 실업률 통계 | 성/연령별 실업률 | ✅ |
| "GDP" | GDP 통계 | 국내총생산 | ✅ |
| "물가" | 물가지수 | 소비자물가 등락률 | ✅ |
| "출산율" | 출산율 통계 | 합계출산율 | ✅ |
| "서울 실업률" | 지역별 실업률 | 행정구역별 실업률 | ✅ |

**원인 (당시)**:
- KOSIS API 검색 알고리즘이 "인구" 키워드에 부양비/노령화 통계를 상위 반환
- 검색 결과 후처리에서 통계명 우선순위 조정 필요

**개선안 (아직 search_statistics 경로에 미적용)**:
- 키워드별 `PRIORITY_TABLES`로 검색 후 대표 테이블 상위 배치
- Python v2.0: `quick_stats` 별칭으로 **즉답 경로**는 우회됨. **탐색 경로는 미적용**

---

### 2. get_table_info - usageHint 지역코드 오류

**당시 문제**: usageHint에 통계표마다 다른 지역코드 체계가 하드코딩됨.

**Python v2.0**: ✅ 메타 API 동적 추출로 해결.

---

### 3. 추천 통계 - population 토픽 핵심 누락

**당시 기대**: 주민등록인구현황, 시도별 총인구, 인구동태건수, 합계출산율, 고령인구비율

**Python v2.0**: `get_statistics_list(recommendedTopic="population")` — 주민등록인구·합계출산율 2개. ⚠️ 부분 해결.

---

### 4. compare_statistics - 다중 지역 비교 실패

**당시**: `objL1: "11+21"` (서울+부산) 형식 실패, 에러 메시지 불친절.

**Python v2.0**: ⚠️ 동일 패턴 미구현. 대신 `chain_compare_regions`로 자연어 다지역 비교는 별도 제공.

---

### 5. LLM 사용 플로우 - 단계가 너무 많음

**당시**: search → table_info → get_statistics_data 등 5~6단계.

**Python v2.0**: `quick_stats`·`quick_trend`·chain 3종으로 ✅ 우회. 프롬프트/도구 설명이 search 경로를 유도하면 ⚠️ 재발 가능.

---

## 원본 테스트 결과 요약

| 카테고리 | 테스트 수 | 성공 | 실패 | 성공률 |
|----------|----------|------|------|--------|
| 자연어 검색 | 11 | 6 | 5 | 55% |
| 테이블 정보 조회 | 3 | 3 | 0 | 100% |
| 데이터 조회 | 4 | 4 | 0 | 100% |
| 비교 분석 | 2 | 1 | 1 | 50% |
| **전체** | **20** | **14** | **6** | **70%** |

→ Python v2.0에서 **라이브 재측정 없음**. 위 수치는 TypeScript 당시 기준.

---

## 결론

- **quick_stats 중심 UX**는 TypeScript 대비 크게 개선됨 (별칭, 자치구 라우팅, chain 도구).
- **search_statistics 탐색 경로·compare_statistics 다중 objL1·추천 토픽 품질**은 코드상 **아직 미해결 또는 부분 해결**.
- 삭제 전 「다 해결됐다」고 단정한 것은 **잘못**이었음. 본 문서는 검증 상태를 명시해 유지.
