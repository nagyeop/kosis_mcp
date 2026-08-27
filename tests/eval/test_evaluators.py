"""L2 tests for Langfuse item evaluator."""

from kosis_mcp.eval.evaluators import item_evaluator


def test_item_evaluator_single_table():
    scores = item_evaluator(
        input={"query": "test"},
        output={
            "predicted_action": "single_table",
            "ranked_table_ids": ["DT_1B08024", "DT_X"],
        },
        expected_output={
            "expected_action": "single_table",
            "gold_table_ids": ["DT_1B08024"],
            "primary_gold_table_id": "DT_1B08024",
            "hard_negative_ids": ["DT_X"],
        },
    )
    by_name = {s.name: s.value for s in scores}
    assert by_name["recall_at_5"] == 1.0
    assert by_name["top1"] == 1.0
    assert by_name["hn_violation"] == 1.0


def test_item_evaluator_exclude_scores_special_action():
    scores = item_evaluator(
        input={"query": "그거 말고"},
        output={"predicted_action": "single_table", "ranked_table_ids": ["DT_X"]},
        expected_output={
            "expected_action": "exclude",
            "gold_table_ids": [],
            "primary_gold_table_id": "",
            "hard_negative_ids": [],
        },
    )
    by_name = {s.name: s.value for s in scores}
    assert by_name["overall_action"] == 0.0
    assert by_name["special_action"] == 0.0
    assert "recall_at_5" not in by_name
