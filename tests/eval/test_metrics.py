"""L2 tests for search eval metrics."""

from kosis_mcp.eval.metrics import (
    hn_violation,
    mrr_at_k,
    multi_gold_recall,
    ndcg_at_k,
    recall_at_k,
    top1,
)


def test_recall_at_5_hit():
    ranked = ["A", "B", "C", "D", "E"]
    assert recall_at_k(ranked, ["C"], k=5) == 1.0


def test_recall_at_5_miss():
    ranked = ["A", "B", "C", "D", "E"]
    assert recall_at_k(ranked, ["Z"], k=5) == 0.0


def test_top1_primary():
    assert top1(["DT_1", "DT_2"], "DT_1", ["DT_1", "DT_2"]) == 1.0
    assert top1(["DT_2", "DT_1"], "DT_1", ["DT_1", "DT_2"]) == 0.0


def test_mrr_at_10():
    ranked = ["X", "Y", "GOLD", "Z"]
    assert mrr_at_k(ranked, ["GOLD"], k=10) == 1 / 3


def test_ndcg_at_10():
    ranked = ["X", "Y", "GOLD"]
    score = ndcg_at_k(ranked, ["GOLD"], k=10)
    assert 0.0 < score < 1.0


def test_hn_violation():
    assert hn_violation(["A", "HN", "B"], ["HN"], k=10) == 1.0
    assert hn_violation(["A", "B"], ["HN"], k=10) == 0.0


def test_multi_gold_recall():
    assert multi_gold_recall(["A", "C", "X"], ["A", "B", "C", "D"]) == 0.5
