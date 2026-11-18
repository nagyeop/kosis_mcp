#!/usr/bin/env python3
"""gold 라벨 검토용 '허용 후보' 제안 → tests/testset/alternates_review.json.

각 gold 항목의 검색 상위 표 중 gold가 아닌 표 가운데, gold 표와 같은 통계조사(statId/statName)이거나
표 이름의 핵심어가 겹치는 표를 후보로 뽑는다(이름 60% 이상, 또는 같은 조사이면서 1/3 이상). 사람이 `approve`를 true/false로 채운 뒤에만
v3 데이터셋(acceptable_table_ids)에 반영한다. 이 스크립트는 라벨 JSON을 바꾸지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
TESTSET = ROOT / "tests" / "testset"
SOURCES = {
    "gold": TESTSET / "gold_queries.json",
    "ops-gold": TESTSET / "ops_gold_queries.json",
    "edge": TESTSET / "edge_queries.json",
}
OUT = TESTSET / "alternates_review.json"
TOP_N = 5
NAME_OVERLAP = 0.6
SURVEY_OVERLAP = 0.34


def _name_tokens(name: str) -> set[str]:
    from kosis_mcp.population_search.terms import analyze

    return set(analyze(name.replace("(", " ").replace(")", " ").replace("/", " "))["core"])


async def _gold_names(client, ids: list[str], rows: list[dict]) -> dict[str, dict]:
    by_id = {r["tableId"]: r for r in rows}
    out: dict[str, dict] = {}
    for tid in ids:
        if tid in by_id:
            out[tid] = {"tableName": by_id[tid].get("tableName"), "statName": by_id[tid].get("statName")}
            continue
        try:
            hits = await client.search_statistics(tid, result_count=5)
            hit = next((h for h in hits if h.get("TBL_ID") == tid), None)
        except Exception:
            hit = None
        out[tid] = {"tableName": (hit or {}).get("TBL_NM"), "statName": (hit or {}).get("STAT_NM")}
    return out


async def suggest(sets: list[str]) -> list[dict]:
    from kosis_mcp.client import get_kosis_client
    from kosis_mcp.population_search.categories import category_of
    from kosis_mcp.population_search.retrieve import api_search_candidates

    client = get_kosis_client()
    out: list[dict] = []
    for name in sets:
        for row in json.loads(SOURCES[name].read_text(encoding="utf-8")):
            gold = row.get("gold_table_ids") or []
            if not gold:
                continue
            rows, _terms, _ = await api_search_candidates(row["query"], limit=30)
            scope = row.get("scope_category")
            if scope:
                rows = [r for r in rows if category_of(r) == scope]
            gold_meta = await _gold_names(client, gold, rows)
            gold_stats = {m.get("statName") for m in gold_meta.values() if m.get("statName")}
            gold_tokens = [_name_tokens(m.get("tableName") or "") for m in gold_meta.values()]
            alternates = []
            for r in rows[:TOP_N]:
                if r["tableId"] in gold or r["tableId"] in (row.get("hard_negative_ids") or []):
                    continue
                toks = _name_tokens(r.get("tableName") or "")
                overlap = max(
                    (len(toks & g) / max(len(g), 1) for g in gold_tokens if g), default=0.0
                )
                same_survey = r.get("statName") in gold_stats
                # 같은 조사라도 범위가 넓으면(인구총조사 등) 무관한 표가 섞인다 → 이름도 일부 겹쳐야 한다.
                if overlap >= NAME_OVERLAP or (same_survey and overlap >= SURVEY_OVERLAP):
                    reasons = [f"name_overlap={overlap:.2f}", *(["same_survey"] if same_survey else [])]
                    alternates.append(
                        {
                            "tableId": r["tableId"],
                            "tableName": r.get("tableName"),
                            "statName": r.get("statName"),
                            "periodRange": [r.get("startPeriod"), r.get("endPeriod")],
                            "reason": reasons,
                            "approve": None,
                        }
                    )
            if alternates:
                out.append(
                    {
                        "source_set": name,
                        "query_id": row["query_id"],
                        "query": row["query"],
                        "gold": gold_meta,
                        "alternates": alternates,
                    }
                )
    return out


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sets", nargs="+", default=list(SOURCES), choices=list(SOURCES))
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    review = asyncio.run(suggest(args.sets))
    args.out.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = sum(len(r["alternates"]) for r in review)
    print(f"{len(review)} items, {n} alternates → {args.out}")


if __name__ == "__main__":
    main()
