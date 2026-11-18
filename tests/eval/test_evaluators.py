"""L2 tests for Langfuse item evaluator."""

from kosis_mcp.eval.evaluators import item_evaluator


def _scores(output, expected_action, gold=(), primary="", hard_negatives=()):
    scores = item_evaluator(
        input={"query": "test"},
        output=output,
        expected_output={
            "expected_action": expected_action,
            "gold_table_ids": list(gold),
            "primary_gold_table_id": primary,
            "hard_negative_ids": list(hard_negatives),
        },
    )
    return {s.name: s.value for s in scores}


def test_single_table_retrieval_vs_decision():
    by_name = _scores(
        {
            "response_family": "action",
            "predicted_action": "single_table",
            "ranked_table_ids": ["DT_X", "DT_1B08024"],
            "selected_table_ids": ["DT_X"],
        },
        "single_table",
        gold=["DT_1B08024"],
        primary="DT_1B08024",
        hard_negatives=["DT_Y"],
    )
    assert by_name["recall_at_5"] == 1.0
    assert by_name["top1"] == 0.0
    assert by_name["top1_any_gold"] == 0.0
    assert by_name["overall_action"] == 1.0


def test_top1_any_gold_accepts_non_primary_gold():
    by_name = _scores(
        {"response_family": "action", "predicted_action": "single_table",
         "ranked_table_ids": ["DT_B"], "selected_table_ids": ["DT_B"]},
        "single_table",
        gold=["DT_A", "DT_B"],
        primary="DT_A",
    )
    assert by_name["top1"] == 0.0
    assert by_name["top1_any_gold"] == 1.0


def test_hn_in_candidates_is_not_a_selected_violation():
    by_name = _scores(
        {"response_family": "action", "predicted_action": "single_table",
         "ranked_table_ids": ["DT_A", "DT_HN"], "selected_table_ids": ["DT_A"]},
        "single_table",
        gold=["DT_A"],
        primary="DT_A",
        hard_negatives=["DT_HN"],
    )
    assert by_name["hn_violation"] == 1.0
    assert by_name["hn_selected"] == 0.0


def test_multi_exact_set_uses_selected_tables():
    by_name = _scores(
        {"response_family": "action", "predicted_action": "multi_table",
         "ranked_table_ids": ["DT_A", "DT_B", "DT_C"], "selected_table_ids": ["DT_A", "DT_B"]},
        "multi_table",
        gold=["DT_A", "DT_B"],
    )
    assert by_name["multi_exact_set"] == 1.0
    assert by_name["multi_selected_recall"] == 1.0


def test_non_action_tools_get_no_action_scores():
    by_name = _scores(
        {"response_family": "candidate", "predicted_action": "single_table",
         "ranked_table_ids": ["DT_A"]},
        "single_table",
        gold=["DT_A"],
        primary="DT_A",
    )
    assert "overall_action" not in by_name
    assert by_name["top1"] == 1.0
