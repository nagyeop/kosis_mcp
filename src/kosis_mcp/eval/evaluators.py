"""Langfuse SDK item evaluator for population search experiments.

Run-level averages / slice views: use ``result.format()`` and the Langfuse
Dataset Run UI (scores + item metadata filters). Do not reimplement here.
"""

from __future__ import annotations

from typing import Any

from langfuse import Evaluation

from kosis_mcp.eval import metrics


# 2: ranked(검색) vs selected(결정) 분리, action 점수는 action을 내는 tool만
EVALUATOR_VERSION = "2"


def item_evaluator(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs: Any,
) -> list[Evaluation]:
    """Retrieval metrics read ranked_table_ids (tables + candidates); decision
    metrics read selected_table_ids; action metrics apply only to tools that
    return an action."""
    exp = expected_output or {}
    out = output if isinstance(output, dict) else {}
    ranked = out.get("ranked_table_ids") or []
    selected = out.get("selected_table_ids")
    if selected is None:
        selected = ranked[:1]
    decides_action = out.get("response_family") == "action"
    predicted = out.get("predicted_action", "unknown")
    expected_action = exp.get("expected_action", "")
    gold = exp.get("gold_table_ids") or []
    primary = exp.get("primary_gold_table_id") or ""
    hard_negatives = exp.get("hard_negative_ids") or []

    scores: list[Evaluation] = []

    if expected_action == "single_table":
        scores.extend(
            [
                Evaluation(name="recall_at_5", value=metrics.recall_at_k(ranked, gold, k=5)),
                Evaluation(name="mrr_at_10", value=metrics.mrr_at_k(ranked, gold, k=10)),
                Evaluation(name="ndcg_at_10", value=metrics.ndcg_at_k(ranked, gold, k=10)),
                Evaluation(name="top1", value=metrics.top1(selected, primary, gold)),
                Evaluation(name="top1_any_gold", value=metrics.top1(selected, "", gold)),
            ]
        )

    if expected_action == "multi_table":
        scores.extend(
            [
                Evaluation(name="multi_exact_set", value=float(set(selected) == set(gold))),
                Evaluation(
                    name="multi_selected_recall",
                    value=metrics.multi_gold_recall(selected, gold),
                ),
                Evaluation(
                    name="multi_gold_recall",
                    value=metrics.multi_gold_recall(ranked, gold),
                ),
            ]
        )

    if hard_negatives:
        scores.extend(
            [
                Evaluation(
                    name="hn_violation",
                    value=metrics.hn_violation(ranked, hard_negatives, k=10),
                ),
                Evaluation(
                    name="hn_selected",
                    value=metrics.hn_violation(selected, hard_negatives, k=len(selected)),
                ),
            ]
        )

    if decides_action:
        matched = float(predicted == expected_action)
        scores.append(Evaluation(name="overall_action", value=matched))
        if expected_action in ("clarify", "exclude", "no_exact_table"):
            scores.append(Evaluation(name="special_action", value=matched))

    return scores
