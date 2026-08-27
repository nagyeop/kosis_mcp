"""Normalize tool responses into eval harness outcomes."""

from __future__ import annotations

import re
from typing import Any

# tblId=DT_..., KOSIS DT_..., bare DT_/TX_ table ids in prose
_TABLE_ID_RE = re.compile(
    r"(?:tblId=|KOSIS\s+)?((?:DT_|TX_)[A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_TABLE_ID_KEYS = frozenset({"tableId", "tblId", "TBL_ID"})
_MODE_PRIMARY = {
    "direct_search": ("results", "search_statistics"),
    "direct_list": ("recommendations", "get_statistics_list"),
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


def normalize_outcome(mode: str, raw: dict[str, Any]) -> dict[str, Any]:
    if mode == "direct_quick":
        ranked = extract_table_ids(raw)
        tool_path = ["quick_stats"]
    elif mode in _MODE_PRIMARY:
        list_key, tool_name = _MODE_PRIMARY[mode]
        primary = [
            table_id
            for row in (raw.get(list_key) or [])
            if (table_id := row.get("tableId"))
        ]
        ranked = []
        seen: set[str] = set()
        for table_id in primary + extract_table_ids(raw):
            if table_id and table_id not in seen:
                seen.add(table_id)
                ranked.append(table_id)
        tool_path = [tool_name]
    else:
        raise ValueError(f"unsupported mode: {mode}")

    return {
        "predicted_action": "no_exact_table" if not ranked else "single_table",
        "ranked_table_ids": ranked,
        "tool_path": tool_path,
    }
