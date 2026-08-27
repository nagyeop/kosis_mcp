"""Deterministic search-quality metrics (Langfuse-independent)."""

from __future__ import annotations

import math
from typing import Sequence


def recall_at_k(ranked: Sequence[str], gold: Sequence[str], k: int = 5) -> float:
    """1.0 if any gold table appears in top-k, else 0.0."""
    if not gold:
        return 0.0
    return 1.0 if set(ranked[:k]).intersection(gold) else 0.0


def top1(ranked: Sequence[str], primary: str, gold: Sequence[str]) -> float:
    """1.0 if rank-1 is primary (when set) or any gold table."""
    if not ranked:
        return 0.0
    first = ranked[0]
    if primary:
        return 1.0 if first == primary else 0.0
    return 1.0 if first in gold else 0.0


def mrr_at_k(ranked: Sequence[str], gold: Sequence[str], k: int = 10) -> float:
    if not gold:
        return 0.0
    gold_set = set(gold)
    for i, table_id in enumerate(ranked[:k], start=1):
        if table_id in gold_set:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], gold: Sequence[str], k: int = 10) -> float:
    if not gold:
        return 0.0
    gold_set = set(gold)

    def dcg(relevances: Sequence[float]) -> float:
        return sum((2**rel - 1) / math.log2(i + 1) for i, rel in enumerate(relevances[:k], start=1))

    relevances = [1.0 if table_id in gold_set else 0.0 for table_id in ranked[:k]]
    idcg = dcg([1.0] * min(len(gold_set), k))
    if idcg == 0.0:
        return 0.0
    return dcg(relevances) / idcg


def hn_violation(ranked: Sequence[str], hard_negatives: Sequence[str], k: int = 10) -> float:
    """1.0 if any hard negative in top-k (violation), else 0.0."""
    if not hard_negatives:
        return 0.0
    return 1.0 if set(ranked[:k]).intersection(hard_negatives) else 0.0


def multi_gold_recall(ranked: Sequence[str], gold: Sequence[str]) -> float:
    if not gold:
        return 0.0
    return len(set(ranked).intersection(gold)) / len(set(gold))
