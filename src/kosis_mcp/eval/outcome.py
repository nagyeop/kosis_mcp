"""Normalize tool responses into eval harness outcomes."""

from __future__ import annotations

import re
from typing import Any

from kosis_mcp.population_search.schema import VALID_ACTIONS

# tblId=DT_..., KOSIS DT_..., bare DT_/TX_ table ids in prose
_TABLE_ID_RE = re.compile(
    r"(?:tblId=|KOSIS\s+)?((?:DT_|TX_)[A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_TABLE_ID_KEYS = frozenset({"tableId", "tblId", "TBL_ID"})

# Legacy mode → tool name (CLI alias only)
MODE_TOOL_ALIASES = {
    "direct_search": "find_tables",
    "direct_quick": "quick_stats",
    "direct_list": "browse_statistics",
}


def extract_table_ids(obj: Any) -> list[str]:
    """Walk JSON-like response and collect table ids in discovery order (deduped)."""
    found: list[str] = []
    seen: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _TABLE_ID_KEYS and isinstance(value, str):
                    if value and value not in seen:
                        seen.add(value)
                        found.append(value)
                else:
                    _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)
        elif isinstance(node, str):
            for match in _TABLE_ID_RE.finditer(node):
                table_id = match.group(1)
                if table_id and table_id not in seen:
                    seen.add(table_id)
                    found.append(table_id)

    _walk(obj)
    return found


def detect_response_family(raw: dict[str, Any]) -> str:
    action = raw.get("action")
    if isinstance(action, str) and action in VALID_ACTIONS:
        return "action"
    if "candidates" in raw:
        return "candidate"
    if "recommendations" in raw:
        return "list"
    if "verified" in raw:
        return "verify"
    source = raw.get("source")
    if isinstance(source, dict) and source.get("tableId"):
        return "value"
    if raw.get("value") is not None:
        return "value"
    return "unknown"


def _rank_from_list_key(raw: dict[str, Any], key: str) -> list[str]:
    ranked: list[str] = []
    seen: set[str] = set()
    rows = raw.get(key) or []
    if key == "candidates":
        rows = sorted(rows, key=lambda r: r.get("rank", 999))
    if key == "verified":
        rows = sorted(
            [r for r in rows if r.get("passed")],
            key=lambda r: r.get("score", 0),
            reverse=True,
        )
    for row in rows:
        if not isinstance(row, dict):
            continue
        table_id = row.get("tableId")
        if table_id and table_id not in seen:
            seen.add(table_id)
            ranked.append(table_id)
    for table_id in extract_table_ids(raw):
        if table_id not in seen:
            seen.add(table_id)
            ranked.append(table_id)
    return ranked


def _selected_ids(
    raw: dict[str, Any], family: str, predicted: str, ranked: list[str]
) -> list[str]:
    """Tables the tool committed to; candidate/list/value tools commit to rank 1."""
    if family != "action":
        return ranked[:1]
    if predicted in ("clarify", "no_exact_table"):
        return []
    ids = [t.get("tableId") for t in raw.get("tables") or [] if isinstance(t, dict)]
    return list(dict.fromkeys(i for i in ids if i))


def normalize_outcome(
    raw: dict[str, Any],
    *,
    tool: str | None = None,
) -> dict[str, Any]:
    family = detect_response_family(raw)

    if family == "action":
        ranked = _rank_from_list_key(raw, "tables")
        predicted = raw.get("action", "single_table")
    elif family == "candidate":
        ranked = _rank_from_list_key(raw, "candidates")
        predicted = "no_exact_table" if not ranked else "single_table"
    elif family == "list":
        ranked = _rank_from_list_key(raw, "recommendations")
        predicted = "single_table"
    elif family == "verify":
        ranked = _rank_from_list_key(raw, "verified")
        predicted = "no_exact_table" if not ranked else "single_table"
    elif family == "value" and raw.get("success") is False:
        # 실패한 수치 조회는 source가 있어도 표를 고른 것이 아니다.
        ranked = []
        predicted = "no_exact_table"
    elif family == "value":
        source = raw.get("source") or {}
        primary = source.get("tableId") if isinstance(source, dict) else None
        walked = extract_table_ids(raw)
        ranked = []
        seen: set[str] = set()
        if primary:
            ranked.append(primary)
            seen.add(primary)
        for table_id in walked:
            if table_id not in seen:
                seen.add(table_id)
                ranked.append(table_id)
        predicted = "no_exact_table" if not ranked else "single_table"
    else:
        ranked = extract_table_ids(raw)
        predicted = "no_exact_table" if not ranked else "single_table"

    if predicted not in VALID_ACTIONS:
        predicted = "single_table" if ranked else "no_exact_table"

    out = {
        "predicted_action": predicted,
        "ranked_table_ids": ranked,
        "selected_table_ids": _selected_ids(raw, family, predicted, ranked),
        "tool_path": [tool] if tool else [],
        "response_family": family,
    }
    if raw.get("isFallback"):
        out["is_fallback"] = True
        out["fallback_region"] = raw.get("fallbackRegion")
    return out


def normalize_outcome_legacy(mode: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Map deprecated --mode to tool-based normalize."""
    tool = MODE_TOOL_ALIASES.get(mode)
    if tool is None:
        raise ValueError(f"unsupported mode: {mode}")
    return normalize_outcome(raw, tool=tool)
