# KOSIS MCP 사용 가이드

> AI에게 한국 통계를 물어보세요. 자연스러운 질문만으로 KOSIS 공식 수치를 조회할 수 있습니다.

상세 설치·도구 목록·변경 이력은 [README.md](../README.md)를 참고하세요.

---

## 이게 뭔가요?

**KOSIS MCP**는 Claude Desktop, Cursor 등 MCP를 지원하는 AI가 **국가데이터처 KOSIS 공식 통계**를 실시간 조회하게 해주는 도구입니다.

| 질문 예시 | 얻을 수 있는 정보 |
|----------|-----------------|
| "한국 인구가 몇 명이야?" | 최신 인구 통계 |
| "서울 출산율 추이 보여줘" | 시계열 추세·변화율 |
| "부산과 대구 실업률 비교해줘" | 지역별 비교 |
| "광진구 고용률 알려줘" | 자치구 단위 정밀 수치 |

데이터 출처: [KOSIS 국가통계포털](https://kosis.kr) OpenAPI

---

## 설치하기

### 준비물

1. **Cursor IDE** 또는 **Claude Desktop** (MCP 지원)
2. **Python 3.11+**
3. **KOSIS API 키** — [공유서비스](https://kosis.kr/openapi)에서 무료 발급

### Step 1: 프로젝트 설치

```bash
git clone https://github.com/chrisryugj/kosis-mcp.git
cd kosis-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

프로젝트 루트 `.env`에 `KOSIS_API_KEY=발급받은_키`를 넣어도 됩니다 (`.env.example` 참고).

### Step 2: Cursor / Claude Desktop에 연결 (stdio)

`~/.cursor/mcp.json` (또는 Claude Desktop MCP 설정):

```json
{
  "mcpServers": {
    "kosis-mcp": {
      "command": "/절대경로/kosis-mcp/.venv/bin/kosis-mcp",
      "args": [],
      "env": { "KOSIS_API_KEY": "발급받은_키" }
    }
  }
}
```

원클릭 등록:

```bash
export KOSIS_API_KEY=발급받은_키
bash install.sh --client cursor
```

### Step 3: HTTP 서버 (선택)

로컬 HTTP:

```bash
KOSIS_API_KEY=... kosis-mcp --http --port 3000
```

Docker Compose·Vercel 배포 방법은 [README.md](../README.md)를 참고하세요.

---

## 어떻게 쓰나요?

대부분의 질문은 **`quick_stats` 한 번**으로 끝납니다. AI가 내부적으로 검색·코드 매칭·데이터 조회를 처리합니다.

| 목적 | 추천 도구 |
|------|----------|
| 단일 수치 ("서울 인구", "광진구 고용률") | `quick_stats` |
| 추세·변화율 ("최근 10년 출산율") | `quick_trend` |
| 전국·동급 지자체 순위 | `quick_rank` |
| 한 지역 종합 브리핑 | `chain_region_brief` |
| 여러 지역·지표 비교 | `chain_compare_regions` |
| 통계표 직접 탐색 | `search_statistics` → `get_table_info` → `get_statistics_data` |

**92개 키워드 + 88개 별칭**을 지원합니다. `집값`→주택가격, `노인`→고령인구, `실업율`(오타) 등도 인식합니다.

---

## 사용 예제

### 기본 조회

> "한국 실업률 알려줘"

AI가 `quick_stats`로 KOSIS를 조회해 수치와 통계표 출처를 함께 답합니다.

### 자치구 정밀 조회

> "광진구 고용률"

전국 230개 이상 자치구·시군을 KOSIS 자치구 단위 표로 직접 조회합니다. 광역시도 평균으로 대체하지 않고, 불가능한 경우에는 그 사실을 명시합니다.

### 추세 분석

> "전국 합계출산율 10년 추세"

`quick_trend`로 변화율, 최고/최저점, 추세 분류를 함께 제공합니다.

### 지역 비교

> "서울이랑 부산 인구 비교해줘"

`chain_compare_regions` 또는 `compare_statistics`로 비교합니다.

---

## 자주 묻는 질문

### 어떤 통계를 조회할 수 있나요?

KOSIS에 등록된 약 7만 개 통계표를 검색·조회할 수 있습니다. 자주 쓰는 92개 키워드는 `quick_stats`로 즉답합니다.

### 데이터는 얼마나 최신인가요?

KOSIS 갱신 주기에 따릅니다. 동일 질의는 6시간 캐시됩니다.

### 무료인가요?

네. KOSIS OpenAPI도 무료입니다.

### 영어로 질문해도 되나요?

`population`, `gdp` 등 영문 별칭도 인식합니다. 통계 데이터 자체는 한국어입니다.

---

## 문제 해결

### "API 키 오류"

1. `KOSIS_API_KEY` 환경변수 또는 `.env` 설정 확인
2. 키 앞뒤 공백·따옴표 제거
3. MCP 설정의 `env` 블록에 키가 전달되는지 확인

### "통계를 찾을 수 없습니다"

1. 다른 키워드 시도 — `출산율`, `합계출산율`, `출생아수`
2. 지역명 추가 — `서울 인구`, `광진구 고용률`
3. `search_statistics`로 통계표 검색

### MCP가 연결되지 않을 때

1. Cursor / Claude Desktop 완전 재시작
2. `kosis-mcp` 실행 파일 경로가 `.venv/bin/kosis-mcp`인지 확인
3. Python 3.11 이상 확인 — `python3 --version`

---

## 더 알아보기

- [README.md](../README.md) — 설치 3가지 방법, 14개 도구, 변경 이력
- [KOSIS OpenAPI](https://kosis.kr/openapi)
- [Model Context Protocol](https://modelcontextprotocol.io)
