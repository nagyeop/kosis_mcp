"""statistics_assistant prompt."""

from __future__ import annotations

from kosis_mcp.population_search.categories import CATEGORY_LIST_IDS


def generate_statistics_assistant_prompt(question: str) -> dict:
    categories = ", ".join(CATEGORY_LIST_IDS)
    instructions = f"""[한국 통계 전문가로서 다음 질문에 답변해주세요]

## 사용 가능한 도구

1. **find_tables**: 통계표 찾기 (action + tables[]). category: {categories}
2. **browse_statistics**: 분야별 목록 트리 둘러보기
3. **get_table_info / explain_statistic**: 표 분류·항목 코드 / 통계 정의·인용 각주
4. **get_statistics_data**: 찾은 표(orgId+tableId)의 데이터 조회
5. **analyze_trend / compare_values**: find_tables 결과 표(1개 이상)의 시계열 추세 / 같은 시점 지역·항목 비교(순위·비중·파생 지표)
6. **quick_stats / quick_trend / quick_rank / compare_regions / region_brief / policy_indicator**: 대표 지표 키워드 지름길 (표 ID 불필요)

## 질문
{question}

---
통계 데이터의 출처와 단위를 명시하고, 최신 데이터 기준으로 답변해주세요."""
    return {
        "messages": [
            {"role": "user", "content": {"type": "text", "text": instructions}}
        ]
    }
