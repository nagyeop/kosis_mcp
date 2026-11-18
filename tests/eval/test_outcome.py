"""L2 tests for outcome normalization."""

from kosis_mcp.eval.outcome import (
    detect_response_family,
    extract_table_ids,
    normalize_outcome,
    normalize_outcome_legacy,
)


def test_detect_response_family_matrix():
    assert detect_response_family({"action": "single_table", "tables": []}) == "action"
    assert detect_response_family({"candidates": []}) == "candidate"
    assert detect_response_family({"recommendations": []}) == "list"
    assert detect_response_family({"verified": []}) == "verify"
    assert detect_response_family({"source": {"tableId": "DT_X"}}) == "value"


def test_normalize_candidate_outcome():
    raw = {
        "success": True,
        "candidates": [
            {"tableId": "DT_1", "rank": 1},
            {"tableId": "DT_2", "rank": 2},
            {"tableId": "DT_1", "rank": 3},
        ],
    }
    out = normalize_outcome(raw, tool="search_statistics")
    assert out["predicted_action"] == "single_table"
    assert out["ranked_table_ids"] == ["DT_1", "DT_2"]
    assert out["response_family"] == "candidate"
    assert out["tool_path"] == ["search_statistics"]


def test_normalize_candidate_outcome_empty():
    out = normalize_outcome({"candidates": []}, tool="search_statistics")
    assert out["predicted_action"] == "no_exact_table"
    assert out["ranked_table_ids"] == []


def test_normalize_action_outcome():
    raw = {
        "action": "multi_table",
        "tables": [{"tableId": "DT_A"}, {"tableId": "DT_B"}],
    }
    out = normalize_outcome(raw, tool="find_tables")
    assert out["predicted_action"] == "multi_table"
    assert out["ranked_table_ids"] == ["DT_A", "DT_B"]
    assert out["selected_table_ids"] == ["DT_A", "DT_B"]
    assert out["response_family"] == "action"


def test_selected_ids_exclude_candidates_and_clarify_preview():
    raw = {
        "action": "single_table",
        "tables": [{"tableId": "DT_A"}],
        "candidates": [{"tableId": "DT_B"}, {"tableId": "DT_C"}],
    }
    out = normalize_outcome(raw, tool="find_tables")
    assert out["ranked_table_ids"] == ["DT_A", "DT_B", "DT_C"]
    assert out["selected_table_ids"] == ["DT_A"]

    clarify = normalize_outcome(
        {"action": "clarify", "tables": [{"tableId": "DT_A"}]}, tool="find_tables"
    )
    assert clarify["ranked_table_ids"] == ["DT_A"]
    assert clarify["selected_table_ids"] == []


def test_selected_ids_for_candidate_family_is_rank1():
    out = normalize_outcome(
        {"candidates": [{"tableId": "DT_A", "rank": 1}, {"tableId": "DT_B", "rank": 2}]},
        tool="find_tables",
    )
    assert out["selected_table_ids"] == ["DT_A"]


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


def test_normalize_value_outcome_source_first():
    raw = {
        "success": True,
        "answer": "서울 인구는 … (KOSIS DT_1B040A3)",
        "source": {"orgId": "101", "tableId": "DT_1B040A3"},
    }
    out = normalize_outcome(raw, tool="quick_stats")
    assert out["predicted_action"] == "single_table"
    assert out["ranked_table_ids"][0] == "DT_1B040A3"
    assert out["response_family"] == "value"


def test_normalize_value_outcome_fail_note_with_table_id():
    raw = {
        "success": False,
        "answer": "데이터 없음",
        "note": "테이블: 주민등록인구 (DT_1B040A3)",
    }
    out = normalize_outcome(raw, tool="quick_stats")
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
    out = normalize_outcome(raw, tool="get_statistics_list")
    assert out["ranked_table_ids"] == ["DT_REC1", "DT_REC2", "DT_EXTRA"]
    assert out["response_family"] == "list"


def test_normalize_outcome_legacy_mode_alias():
    raw = {"candidates": [{"tableId": "DT_A", "rank": 1}]}
    out = normalize_outcome_legacy("direct_search", raw)
    assert out["tool_path"] == ["find_tables"]
    assert out["ranked_table_ids"] == ["DT_A"]


def test_failed_value_lookup_selects_nothing():
    from kosis_mcp.eval.outcome import normalize_outcome

    raw = {"success": False, "answer": "데이터 없음", "source": {"orgId": "101", "tableId": "DT_X"}}
    out = normalize_outcome(raw, tool="quick_stats")
    assert out["selected_table_ids"] == [] and out["predicted_action"] == "no_exact_table"


def test_fallback_flag_is_recorded():
    from kosis_mcp.eval.outcome import normalize_outcome

    raw = {"success": True, "value": "1", "source": {"tableId": "DT_A"}, "isFallback": True, "fallbackRegion": "전국"}
    out = normalize_outcome(raw, tool="quick_stats")
    assert out["is_fallback"] and out["fallback_region"] == "전국"
