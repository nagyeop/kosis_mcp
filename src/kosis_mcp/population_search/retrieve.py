"""retrieve — KOSIS 통계표 검색 (검색어 생성 → 검색어별 결과 번갈아 합치기)."""

from __future__ import annotations

from typing import Any, Literal

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import get_kosis_client
from kosis_mcp.population_search.axes import axes_to_terms
from kosis_mcp.population_search.terms import build_search_terms
from kosis_mcp.tools.more_tools import _merge_search_results
from kosis_mcp.utils.query_parser import parse_query


def _with_axis_term(terms: list[str], axes: list[dict[str, Any]]) -> list[str]:
    """Prepend one keyword term combining the base term with axis labels."""
    extra = [t for t in axes_to_terms(axes) if t not in terms[0]]
    if not extra:
        return terms
    return [" ".join([terms[0], *extra[:2]])] + terms[:3]


async def api_search_candidates(
    query: str,
    *,
    axes: list[dict[str, Any]] | None = None,
    org_id: str | None = None,
    sort: Literal["RANK", "DATE"] | None = "RANK",
    limit: int = 10,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    client = get_kosis_client()
    cache = get_cache_manager()
    parsed = parse_query(query)
    terms = build_search_terms(query)
    if axes:
        terms = _with_axis_term(terms, axes)
    rows, _per_term = await _merge_search_results(
        cache, client, terms, org_id, sort, limit, parsed
    )
    return rows, terms, parsed
