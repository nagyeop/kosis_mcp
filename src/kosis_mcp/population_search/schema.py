"""Shared response primitives for population search tools."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

PopulationAction = Literal[
    "single_table", "multi_table", "clarify", "no_exact_table"
]

VALID_ACTIONS: frozenset[str] = frozenset(
    {"single_table", "multi_table", "clarify", "no_exact_table"}
)


class TableRef(TypedDict, total=False):
    orgId: str
    tableId: str
    tableName: str


class KosisSource(TableRef, total=False):
    retrievedAt: str
    lastUpdated: str


def build_source(
    org_id: str,
    table_id: str,
    table_name: str,
    *,
    retrieved_at: str | None = None,
    last_updated: str | None = None,
) -> dict[str, str]:
    out: dict[str, str] = {
        "orgId": org_id,
        "tableId": table_id,
        "tableName": table_name,
    }
    if retrieved_at:
        out["retrievedAt"] = retrieved_at
    if last_updated:
        out["lastUpdated"] = last_updated
    return out


def build_candidate_response(
    query: str,
    rows: list[dict[str, Any]],
    *,
    backends: list[str] | None = None,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        table_id = row.get("tableId") or row.get("TBL_ID")
        if not table_id:
            continue
        item: dict[str, Any] = {
            "orgId": str(row.get("orgId") or row.get("ORG_ID") or ""),
            "tableId": str(table_id),
            "tableName": str(row.get("tableName") or row.get("TBL_NM") or ""),
            "rank": rank,
        }
        stat = row.get("statName") or row.get("STAT_NM")
        if stat:
            item["statName"] = str(stat)
        view = row.get("viewCode") or row.get("VW_CD")
        if view:
            item["viewCode"] = str(view)
        candidates.append(item)
    out: dict[str, Any] = {
        "success": True,
        "query": query,
        "candidates": candidates,
        "totalCount": len(candidates),
    }
    if backends:
        out["backends"] = backends
    return out


def build_action_response(
    query: str,
    action: PopulationAction,
    tables: list[dict[str, Any]],
    *,
    clarify: dict[str, Any] | None = None,
    no_exact: dict[str, Any] | None = None,
    debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "success": True,
        "query": query,
        "action": action,
        "tables": tables,
    }
    if clarify:
        out["clarify"] = clarify
    if no_exact:
        out["noExact"] = no_exact
    if debug:
        out["debug"] = debug
    return out
