"""L2 tests for population search action rules."""

from kosis_mcp.population_search.action import decide_action
from kosis_mcp.population_search.schema import build_candidate_response


def test_build_candidate_response_rank():
    raw = build_candidate_response(
        "인구",
        [
            {"orgId": "101", "tableId": "DT_A", "tableName": "A"},
            {"orgId": "101", "tableId": "DT_B", "tableName": "B"},
        ],
    )
    assert raw["candidates"][0]["rank"] == 1
    assert raw["candidates"][1]["tableId"] == "DT_B"


def test_decide_action_no_exact():
    action, tables, clarify, no_exact = decide_action("희귀 표", [])
    assert action == "no_exact_table"
    assert tables == []
    assert no_exact is not None


def test_decide_action_multi_hint():
    verified = [
        {
            "orgId": "101",
            "tableId": "DT_1",
            "tableName": "A",
            "score": 0.9,
            "passed": True,
        },
        {
            "orgId": "101",
            "tableId": "DT_2",
            "tableName": "B",
            "score": 0.8,
            "passed": True,
        },
    ]
    action, tables, _clarify, _no_exact = decide_action(
        "인구와 출산율 표 함께", verified, multi=True
    )
    assert action == "multi_table"
    assert len(tables) == 2
    # 복수 요청이 아니면 2위(0.8 < 0.9×0.95)는 붙이지 않는다.
    action, tables, _c, _n = decide_action("인구 표", verified)
    assert action == "single_table" and len(tables) == 1


def test_clarify_rule_only_in_population_scope():
    verified = [{"orgId": "101", "tableId": "DT_1", "tableName": "A", "score": 0.9, "passed": True}]
    assert decide_action("어린이집 수", verified, population_scope=False)[0] == "single_table"
    assert decide_action("어린이 인구", verified, population_scope=True)[0] == "clarify"
