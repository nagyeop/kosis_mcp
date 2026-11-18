"""extract_population_constraints — structured constraints from query."""

from __future__ import annotations

from typing import Any

from kosis_mcp.population_search.axes import extract_axes
from kosis_mcp.utils.query_parser import parse_query


async def extract_population_constraints(query: str) -> dict[str, Any]:
    parsed = parse_query(query)
    constraints: dict[str, Any] = {
        "topics": parsed.get("topics") or [],
        "axes": extract_axes(query),
    }
    if parsed.get("timeRange"):
        constraints["timeRange"] = parsed["timeRange"]
    return {"success": True, "query": query, "constraints": constraints}
