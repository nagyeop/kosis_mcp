"""FastMCP server registration smoke tests."""

import os

import pytest

os.environ.setdefault("KOSIS_API_KEY", "test-key-for-unit-tests")

from kosis_mcp.server import mcp


@pytest.mark.asyncio
async def test_tools_registered():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "quick_stats",
        "quick_trend",
        "quick_rank",
        "explain_statistic",
        "search_statistics",
        "get_statistics_list",
        "get_statistics_data",
        "compare_statistics",
        "analyze_time_series",
        "get_table_info",
        "fetch_kosis_excel",
        "chain_region_brief",
        "chain_compare_regions",
        "chain_policy_indicator",
    }
    assert expected <= names
    assert len(names) == 14


@pytest.mark.asyncio
async def test_resources_registered():
    resources = await mcp.list_resources()
    uris = {str(r.uri) for r in resources}
    assert "kosis://categories/tree" in uris
    assert "kosis://indicators/list" in uris
