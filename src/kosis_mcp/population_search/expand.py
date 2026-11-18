"""expand_population_query — search term expansion."""

from __future__ import annotations

from typing import Any

from kosis_mcp.utils.query_parser import generate_search_terms, parse_query


async def expand_population_query(query: str) -> dict[str, Any]:
    parsed = parse_query(query)
    terms = generate_search_terms(parsed, query) or [query]
    return {
        "success": True,
        "query": query,
        "terms": terms,
        "parsed": {
            k: parsed[k]
            for k in ("topics", "regions", "keywords", "timeRange", "intent")
            if k in parsed
        },
    }
