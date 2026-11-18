"""find_tables — 통계표 찾기 진입점 (검색 → 검증 → action + 후보)."""

from __future__ import annotations

import re
from typing import Any, Literal

from kosis_mcp.population_search.action import MULTI_HINT, decide_action
from kosis_mcp.population_search.axes import (
    build_axis_filter,
    extract_axes,
    merge_axes,
    normalize_axes,
)
from kosis_mcp.population_search.categories import POPULATION, category_counts, category_of
from kosis_mcp.population_search.intent import classify_population_intent
from kosis_mcp.population_search.retrieve import api_search_candidates
from kosis_mcp.population_search.schema import build_action_response
from kosis_mcp.population_search.terms import analyze
from kosis_mcp.population_search.verify import batch_verify_table_candidates
from kosis_mcp.utils.query_parser import REGION_CODES
from kosis_mcp.utils.regions import DISTRICT_TO_PROVINCE, normalize_province_name

Mode = Literal["auto", "fast", "thorough"]

MAX_CANDIDATES = 10
_VERIFY_N = {"fast": 5, "auto": 8, "thorough": 10}
_INTENT_NEXT = {
    "get_value": "수치가 필요하면 tables[0]의 orgId·tableId로 get_statistics_data를 호출하거나, 대표 지표는 quick_stats를 쓰세요.",
    "browse": "분야별로 둘러보려면 browse_statistics를 쓰세요.",
}
# 체언 뒤 접속 조사(와·과·랑·하고)는 뒤에 공백이 있을 때만 — '와이파이' 같은 단어를 자르지 않는다.
_SPLIT_RE = re.compile(r"(?<=[가-힣0-9])(?:와|과|랑|하고)\s+|\s+(?:및|그리고|또는)\s+|\s*,\s*")
_TAIL_RE = re.compile(r"\s*(을|를)?\s*(함께|같이|동시에|각각)\b.*$")


def _is_region_name(token: str) -> bool:
    return token in REGION_CODES or token in DISTRICT_TO_PROVINCE or normalize_province_name(token) != token


def _is_region_only(fragment: str) -> bool:
    core = analyze(fragment)["core"]
    return bool(core) and all(_is_region_name(c) for c in core)


def split_subqueries(query: str) -> list[str]:
    """복수 표 요청을 하위 질의로 나눈다. 꼬리('함께 비교하고 싶어')는 떼고,
    지역만 남은 조각('서울 및 부산 인구'의 '서울')은 다음 조각의 주제를 이어 붙인다."""
    body = _TAIL_RE.sub("", query).strip() or query
    parts = [p.strip() for p in _SPLIT_RE.split(body) if p and p.strip()]
    parts = [p for p in parts if analyze(p)["core"]]
    if len(parts) < 2:
        return [query]
    out: list[str] = []
    for i, p in enumerate(parts):
        if _is_region_only(p) and i + 1 < len(parts):
            topic = [c for c in analyze(parts[i + 1])["core"] if not _is_region_name(c)]
            p = " ".join([p, *topic])
        out.append(p)
    return out


def _key(row: dict[str, Any]) -> tuple[Any, Any]:
    return row.get("orgId"), row.get("tableId")


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        if _key(row) not in seen:
            seen.add(_key(row))
            out.append(row)
    return out


def _table_ref(table: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(table)
    if not row:
        return out
    for key in ("tableName", "statId", "statName", "path"):
        if row.get(key) and not out.get(key):
            out[key] = row[key]
    category = category_of(row)
    if category:
        out["category"] = category
    if row.get("startPeriod") or row.get("endPeriod"):
        out["periodRange"] = {"start": row.get("startPeriod"), "end": row.get("endPeriod")}
    return out


def _rest_candidates(
    tables: list[dict[str, Any]],
    ranked: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Verified order first, then remaining search order; decided tables excluded."""
    by_id = {_key(r): r for r in rows}
    seen = {_key(t) for t in tables}
    out: list[dict[str, Any]] = []
    for item in [*ranked, *rows]:
        key = _key(item)
        if key in seen or not item.get("tableId"):
            continue
        seen.add(key)
        ref = {"orgId": item.get("orgId"), "tableId": item.get("tableId")}
        if item.get("score") is not None:
            ref["confidence"] = item["score"]
        out.append(_table_ref(ref, by_id.get(key)))
    return out[:MAX_CANDIDATES]


def _population_scope(category: str | None, counts: dict[str, int]) -> bool:
    if category:
        return category == POPULATION
    total = sum(counts.values())
    return bool(total) and counts.get(POPULATION, 0) * 2 >= total


async def _find_one(
    query: str,
    *,
    axes: list[dict[str, Any]] | None,
    time_range: str | None,
    mode: Mode,
    category: str | None,
    org_id: str | None,
    multi: bool = False,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], dict | None, dict | None, dict[str, Any]]:
    search_query = f"{query} {time_range}" if time_range else query
    explicit_axes = normalize_axes(axes)
    merged_axes = merge_axes(extract_axes(query), axes)
    where_values = [
        v
        for a in merged_axes
        if a["mode"] == "where"
        for v in a.get("values") or []
        if v not in search_query
    ]
    verify_query = " ".join([search_query, *where_values])

    limit = 10 if mode != "fast" else 5
    verify_n = _VERIFY_N.get(mode, 8)

    # Search terms use explicit axes only; extracted axes feed verification.
    rows, terms, _parsed = await api_search_candidates(
        search_query,
        axes=explicit_axes,
        org_id=org_id,
        limit=limit * 3 if category else limit,
    )
    counts = category_counts(rows)  # 분야 필터 전 분포
    if category:
        rows = [r for r in rows if category_of(r) == category][:limit]
    steps = ["parse", "retrieve"]

    if mode == "fast" or not rows:
        ranked = [
            {
                "orgId": r.get("orgId"),
                "tableId": r.get("tableId"),
                "tableName": r.get("tableName"),
                "statName": r.get("statName"),
                "score": max(0.5, 1.0 - i * 0.05),
                "passed": True,
            }
            for i, r in enumerate(rows[:verify_n])
        ]
        steps.append("rank_fast")
    else:
        raw_candidates = [
            {
                "orgId": r.get("orgId"),
                "tableId": r.get("tableId"),
                "tableName": r.get("tableName"),
                "statName": r.get("statName"),
                "path": r.get("path"),
                "endPeriod": r.get("endPeriod"),
                "searchRank": r.get("searchRank", i),
            }
            for i, r in enumerate(rows[:verify_n])
        ]
        verify_out = await batch_verify_table_candidates(verify_query, raw_candidates)
        ranked = verify_out["verified"]
        steps.append("batch_verify")

    action, tables, clarify, no_exact = decide_action(
        search_query, ranked, population_scope=_population_scope(category, counts), multi=multi
    )
    by_id = {_key(r): r for r in rows}
    tables = [_table_ref(t, by_id.get(_key(t))) for t in tables]
    candidates = _rest_candidates(tables, ranked, rows)
    debug = {
        "terms": terms,
        "backends": ["kosis_api"],
        "steps": steps,
        "categories": counts,
        "axes": merged_axes,
        "axisFilter": build_axis_filter(merged_axes),
    }
    return action, tables, candidates, clarify, no_exact, debug


async def find_tables(
    query: str,
    category: str | None = None,
    axes: list[dict[str, Any]] | None = None,
    time_range: str | None = None,
    mode: Mode = "auto",
    decompose: bool = False,
    org_id: str | None = None,
) -> dict[str, Any]:
    intent = (await classify_population_intent(query))["intent"]
    opts = {
        "axes": axes,
        "time_range": time_range,
        "mode": mode,
        "category": category,
        "org_id": org_id,
    }

    wants_multi = decompose or bool(MULTI_HINT.search(query))
    sub_queries = split_subqueries(query) if wants_multi else [query]
    if len(sub_queries) > 1:
        tables: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        per_query: list[dict[str, Any]] = []
        for sub in sub_queries:
            sub_action, sub_tables, sub_rest, _c, _n, sub_debug = await _find_one(sub, **opts)
            # 하위 질의마다 1위 표 1개. 나머지는 후보로.
            per_query.append(
                {"query": sub, "terms": sub_debug["terms"], "action": sub_action, "tables": len(sub_tables)}
            )
            tables.extend(sub_tables[:1])
            rest.extend([*sub_tables[1:], *sub_rest])
        tables = _dedupe(tables)
        seen = {_key(t) for t in tables}
        candidates = _dedupe([c for c in rest if _key(c) not in seen])[:MAX_CANDIDATES]
        action = "multi_table" if tables else "no_exact_table"
        clarify = None
        no_exact = None if tables else {"reason": "복수 표 요청에 맞는 후보를 찾지 못했습니다."}
        missing = [p["query"] for p in per_query if not p["tables"]]
        debug: dict[str, Any] = {"subQueries": per_query, "steps": ["decompose"]}
        if missing:
            debug["unmatchedSubQueries"] = missing
    else:
        action, tables, candidates, clarify, no_exact, debug = await _find_one(
            query, **opts, multi=wants_multi
        )

    debug["intent"] = intent
    out = build_action_response(
        query, action, tables, clarify=clarify, no_exact=no_exact, debug=debug
    )
    out["candidates"] = candidates
    if intent in _INTENT_NEXT and tables:
        out["next"] = _INTENT_NEXT[intent]
    return out
