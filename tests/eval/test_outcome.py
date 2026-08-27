"""L2 tests for outcome normalization."""

from kosis_mcp.eval.outcome import extract_table_ids, normalize_outcome


def test_normalize_search_outcome_with_results():
    raw = {
        "success": True,
        "results": [
            {"tableId": "DT_1"},
            {"tableId": "DT_2"},
            {"tableId": "DT_1"},
        ],
    }
    out = normalize_outcome("direct_search", raw)
    assert out["predicted_action"] == "single_table"
    assert out["ranked_table_ids"] == ["DT_1", "DT_2"]
    assert out["tool_path"] == ["search_statistics"]


def test_normalize_search_outcome_empty():
    out = normalize_outcome("direct_search", {"results": []})
    assert out["predicted_action"] == "no_exact_table"
    assert out["ranked_table_ids"] == []


def test_extract_table_ids_walk_nested_and_prose():
    raw = {
        "source": {"tableId": "DT_SRC"},
        "note": 'search_statistics("인구") 또는 KOSIS DT_NOTE 참고',
        "answer": "tblId=DT_ANSWER 사용",
        "extra": {"tblId": "DT_TBL"},
    }
    ids = extract_table_ids(raw)
    assert ids[0] == "DT_SRC"
    assert "DT_TBL" in ids
    assert "DT_NOTE" in ids
    assert "DT_ANSWER" in ids


def test_normalize_quick_outcome_success():
    raw = {
        "success": True,
        "answer": "서울 인구는 … (KOSIS DT_1B040A3)",
        "source": {"orgId": "101", "tableId": "DT_1B040A3"},
    }
    out = normalize_outcome("direct_quick", raw)
    assert out["predicted_action"] == "single_table"
    assert out["ranked_table_ids"][0] == "DT_1B040A3"
    assert out["tool_path"] == ["quick_stats"]


def test_normalize_quick_outcome_fail_note_with_table_id():
    raw = {
        "success": False,
        "answer": "데이터 없음",
        "note": "테이블: 주민등록인구 (DT_1B040A3)",
    }
    out = normalize_outcome("direct_quick", raw)
    assert out["ranked_table_ids"] == ["DT_1B040A3"]


def test_normalize_list_outcome_recommendations_first():
    raw = {
        "mode": "recommended",
        "recommendations": [
            {"tableId": "DT_REC1"},
            {"tableId": "DT_REC2"},
        ],
        "note": "also tblId=DT_EXTRA",
    }
    out = normalize_outcome("direct_list", raw)
    assert out["ranked_table_ids"] == ["DT_REC1", "DT_REC2", "DT_EXTRA"]
    assert out["tool_path"] == ["get_statistics_list"]


def test_normalize_outcome_dispatch():
    search = normalize_outcome("direct_search", {"results": [{"tableId": "DT_A"}]})
    assert search["tool_path"] == ["search_statistics"]
    quick = normalize_outcome("direct_quick", {"source": {"tableId": "DT_B"}})
    assert quick["tool_path"] == ["quick_stats"]
    lst = normalize_outcome(
        "direct_list", {"recommendations": [{"tableId": "DT_C"}]}
    )
    assert lst["tool_path"] == ["get_statistics_list"]
