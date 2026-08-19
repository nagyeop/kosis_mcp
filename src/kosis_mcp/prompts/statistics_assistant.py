"""statistics_assistant prompt."""

from __future__ import annotations

from kosis_mcp.tools.more_tools import (
    get_available_recommended_topics,
    get_available_view_codes,
)


def generate_statistics_assistant_prompt(question: str) -> dict:
    topics = get_available_recommended_topics()
    view_codes = get_available_view_codes()
    instructions = f"""[한국 통계 전문가로서 다음 질문에 답변해주세요]

## 사용 가능한 도구

1. **search_statistics**: 키워드로 통계표 검색
2. **get_statistics_list**: 분류별 통계 목록 탐색 ({', '.join(v['code'] for v in view_codes[:6])}…)
3. **get_statistics_data**: 특정 통계표의 데이터 조회
4. **compare_statistics**: 시점별/항목별 통계 비교
5. **analyze_time_series**: 시계열 추세 분석
6. **get_statistics_list (recommendedTopic 옵션)**: 분야별 추천 카드 ({', '.join(t['code'] for t in topics)})
7. **quick_stats / quick_trend / quick_rank / chain_***: 자연어 빠른 조회·추세·순위·브리핑

## 질문
{question}

---
통계 데이터의 출처와 단위를 명시하고, 최신 데이터 기준으로 답변해주세요."""
    return {
        "messages": [
            {"role": "user", "content": {"type": "text", "text": instructions}}
        ]
    }
