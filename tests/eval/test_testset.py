"""L2: testset JSON is upload-ready (same fields as gold_queries)."""

from __future__ import annotations

import json
from pathlib import Path

TESTSET = Path(__file__).resolve().parents[1] / "testset"
REQUIRED = {
    "query_id",
    "query",
    "query_group",
    "expected_action",
    "gold_table_ids",
    "primary_gold_table_id",
    "hard_negative_ids",
}


def _rows(name: str) -> list[dict]:
    return json.loads((TESTSET / name).read_text(encoding="utf-8"))


def test_ops_and_edge_have_gold_schema():
    for name, prefix, n in (
        ("ops_gold_queries.json", "O", 30),
        ("edge_queries.json", "E", 132),
    ):
        rows = _rows(name)
        assert len(rows) == n
        ids = [row["query_id"] for row in rows]
        assert len(ids) == len(set(ids))
        for row in rows:
            missing = REQUIRED - row.keys()
            assert not missing, f"{name} {row.get('query_id')}: {missing}"
            assert row["query_id"].startswith(prefix)
            if row["expected_action"] == "single_table":
                assert row["gold_table_ids"]
