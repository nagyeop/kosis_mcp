"""Langfuse SDK item evaluator for population search experiments.

Run-level averages / slice views: use ``result.format()`` and the Langfuse
Dataset Run UI (scores + item metadata filters). Do not reimplement here.
"""

from __future__ import annotations

from typing import Any

from langfuse import Evaluation

from kosis_mcp.eval import metrics


def item_evaluator(
    *,
    input: Any,
    output: Any,
    expected_output: Any = None,
    metadata: Any = None,
    **kwargs: Any,
) -> list[Evaluation]:
    exp = expected_output or {}
    out = output if isinstance(output, dict) else {}
    ranked = out.get("ranked_table_ids") or []
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
                Evaluation(name="top1", value=metrics.top1(ranked, primary, gold)),
                Evaluation(name="mrr_at_10", value=metrics.mrr_at_k(ranked, gold, k=10)),
                Evaluation(name="ndcg_at_10", value=metrics.ndcg_at_k(ranked, gold, k=10)),
            ]
        )

    if expected_action == "multi_table":
        scores.extend(
            [
                Evaluation(name="multi_exact_set", value=float(set(ranked) == set(gold))),
                Evaluation(
                    name="multi_gold_recall",
                    value=metrics.multi_gold_recall(ranked, gold),
                ),
            ]
        )

    if hard_negatives:
        scores.append(
            Evaluation(
                name="hn_violation",
                value=metrics.hn_violation(ranked, hard_negatives, k=10),
            )
        )

    scores.append(
        Evaluation(
            name="overall_action",
            value=float(predicted == expected_action),
            comment=(
                "clarify/exclude/multi action heuristic limited"
                if expected_action in ("clarify", "exclude", "multi_table")
                else None
            ),
        )
    )

    if expected_action in ("clarify", "exclude", "no_exact_table"):
        scores.append(
            Evaluation(
                name="special_action",
                value=float(predicted == expected_action),
                comment="clarify/exclude: known limitation in direct_* modes"
                if expected_action in ("clarify", "exclude")
                else None,
            )
        )

    return scores
