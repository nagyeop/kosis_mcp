"""action — decide single / multi / clarify / no_exact."""

from __future__ import annotations

import re
from typing import Any, Literal

from kosis_mcp.population_search.schema import PopulationAction

# 복수 표 요청: '함께/같이/동시에/각각' + 실제로 나눌 수 있는 접속(find.split_subqueries가 판정).
MULTI_HINT = re.compile(r"함께|동시에|각각|같이\s*(비교|보)")
_CLARIFY_HINT = re.compile(r"노인|애들|어린이|어디에|어느\s*기준|주민등록.*총조사|총조사.*주민등록")
SECOND_TABLE_RATIO = 0.95


def decide_action(
    query: str,
    verified: list[dict[str, Any]],
    *,
    population_scope: bool = True,
    multi: bool = False,
) -> tuple[PopulationAction, list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    """population_scope: 인구 분야 질의일 때만 인구용 clarify 규칙(노인·어린이, 주민등록 vs 총조사)을 적용.
    multi: 복수 표 요청이지만 하위 질의로 나누지 못한 경우 → 상위 2개."""
    passed = [v for v in verified if v.get("passed")]
    ranked = passed or verified

    if not ranked:
        return (
            "no_exact_table",
            [],
            None,
            {"reason": "조건을 충족하는 통계표 후보를 찾지 못했습니다."},
        )

    if population_scope and _CLARIFY_HINT.search(query):
        questions = [
            "주민등록 기준과 인구주택총조사 기준 중 어느 조사를 원하시나요?",
            "시도·시군구·읍면동 중 어느 행정 단위가 필요하신가요?",
        ]
        preview = [
            {
                "orgId": r["orgId"],
                "tableId": r["tableId"],
                "tableName": r["tableName"],
                "confidence": r.get("score"),
            }
            for r in ranked[:3]
        ]
        return "clarify", preview, {"questions": questions}, None

    if multi:
        tables = [
            {
                "orgId": r["orgId"],
                "tableId": r["tableId"],
                "tableName": r["tableName"],
                "confidence": r.get("score"),
            }
            for r in ranked[:2]
        ]
        return "multi_table", tables, None, None

    top = ranked[0]
    tables = [
        {
            "orgId": top["orgId"],
            "tableId": top["tableId"],
            "tableName": top["tableName"],
            "confidence": top.get("score"),
        }
    ]
    if len(ranked) > 1 and (ranked[1].get("score") or 0) >= (top.get("score") or 0) * SECOND_TABLE_RATIO:
        tables.append(
            {
                "orgId": ranked[1]["orgId"],
                "tableId": ranked[1]["tableId"],
                "tableName": ranked[1]["tableName"],
                "confidence": ranked[1].get("score"),
            }
        )
    return "single_table", tables, None, None
