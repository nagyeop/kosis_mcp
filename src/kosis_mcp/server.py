"""FastMCP server — tools, resources, prompts."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from langfuse import get_client, observe

load_dotenv()

from kosis_mcp.config import SERVER_VERSION, TOOL_COUNT, validate_config
from kosis_mcp.prompts.statistics_assistant import (
    generate_statistics_assistant_prompt,
)
from kosis_mcp.resources.static import (
    get_category_tree_json,
    get_key_indicators_json,
)
from kosis_mcp.tools.fetch_kosis_excel import fetch_kosis_excel
from kosis_mcp.tools.get_table_info import get_table_info
from kosis_mcp.tools.more_tools import (
    chain_compare_regions,
    chain_policy_indicator,
    chain_region_brief,
    explain_statistic,
    get_statistics_list,
    quick_rank,
    quick_trend,
    search_statistics,
)
from kosis_mcp.tools.quick_stats import quick_stats
from kosis_mcp.tools.stats_query import (
    analyze_time_series,
    compare_statistics,
    get_statistics_data,
)

SERVICE = "kosis-mcp"
ANN = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


@lifespan
async def langfuse_lifecycle(_: FastMCP):
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        yield {}
        return
    langfuse = get_client()
    try:
        yield {"langfuse": langfuse}
    finally:
        await asyncio.to_thread(langfuse.shutdown)


mcp = FastMCP(
    "kosis-mcp",
    version=SERVER_VERSION,
    instructions=(
        "한국 국가데이터처 KOSIS OpenAPI 기반 MCP 서버 — 92개 키워드, "
        "17 시도 + 자치구 230+ 라우팅, 시계열·순위·체인 도구."
    ),
    lifespan=langfuse_lifecycle,
)


def _desc(text: str) -> str:
    return f"{SERVICE} — {text}"


@mcp.tool(
    name="quick_stats",
    description=_desc(
        "[빠른조회] 자연어 한 줄 → KOSIS 수치 즉답. 91개 키워드 + 17 시도 + 자치구 라우팅."
    ),
    annotations=ANN,
)
@observe(name="quick_stats", as_type="tool")
async def tool_quick_stats(
    query: str,
    region: str | None = None,
    year: int | None = None,
    period: Literal["Y", "Q", "M"] | None = None,
    month: int | None = None,
    quarter: int | None = None,
) -> dict[str, Any]:
    validate_config()
    return await quick_stats(query, region, year, period, month, quarter)


@mcp.tool(
    name="quick_trend",
    description=_desc("[빠른추세] 자연어 → 시계열 + 증감률 + 최고/최저 + 추세."),
    annotations=ANN,
)
@observe(name="quick_trend", as_type="tool")
async def tool_quick_trend(
    keyword: str, region: str | None = None, yearCount: int | None = None
) -> dict[str, Any]:
    validate_config()
    return await quick_trend(keyword, region, yearCount)


@mcp.tool(
    name="quick_rank",
    description=_desc("[순위] 동급 지자체 대비 전국 순위·백분위."),
    annotations=ANN,
)
@observe(name="quick_rank", as_type="tool")
async def tool_quick_rank(keyword: str, region: str) -> dict[str, Any]:
    validate_config()
    return await quick_rank(keyword, region)


@mcp.tool(
    name="explain_statistic",
    description=_desc("[출처·각주] 통계 정의·작성목적·인용 각주."),
    annotations=ANN,
)
@observe(name="explain_statistic", as_type="tool")
async def tool_explain_statistic(
    keyword: str | None = None,
    orgId: str | None = None,
    tableId: str | None = None,
) -> dict[str, Any]:
    validate_config()
    return await explain_statistic(keyword, orgId, tableId)


@mcp.tool(
    name="search_statistics",
    description=_desc("[검색] 키워드로 KOSIS 통계표 검색."),
    annotations=ANN,
)
@observe(name="search_statistics", as_type="tool")
async def tool_search_statistics(
    query: str,
    orgId: str | None = None,
    sort: Literal["RANK", "DATE"] | None = "RANK",
    limit: int = 10,
) -> dict[str, Any]:
    validate_config()
    return await search_statistics(query, orgId, sort, limit)


@mcp.tool(
    name="get_statistics_list",
    description=_desc("[목록탐색] 주제별/기관별 트리 + 추천 카드."),
    annotations=ANN,
)
@observe(name="get_statistics_list", as_type="tool")
async def tool_get_statistics_list(
    viewCode: str = "MT_ZTITLE",
    parentId: str = "",
    recommendedTopic: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    validate_config()
    return await get_statistics_list(viewCode, parentId, recommendedTopic, limit)


@mcp.tool(
    name="get_statistics_data",
    description=_desc("[직접조회] orgId+tableId로 통계 데이터 조회."),
    annotations=ANN,
)
@observe(name="get_statistics_data", as_type="tool")
async def tool_get_statistics_data(
    orgId: str,
    tableId: str,
    periodType: Literal["Y", "M", "Q", "S", "D", "F", "IR"],
    regionName: str | None = None,
    itemName: str | None = None,
    objL1: str | None = None,
    objL2: str | None = None,
    objL3: str | None = None,
    objL4: str | None = None,
    itemId: str | None = None,
    startPeriod: str | None = None,
    endPeriod: str | None = None,
    recentCount: int | None = None,
) -> dict[str, Any]:
    validate_config()
    return await get_statistics_data(
        orgId,
        tableId,
        periodType,
        regionName,
        itemName,
        objL1,
        objL2,
        objL3,
        objL4,
        itemId,
        startPeriod,
        endPeriod,
        recentCount,
    )


@mcp.tool(
    name="compare_statistics",
    description=_desc("[비교] 동일 표 안 시점/항목 비교."),
    annotations=ANN,
)
@observe(name="compare_statistics", as_type="tool")
async def tool_compare_statistics(
    orgId: str,
    tableId: str,
    compareType: Literal["period", "item"],
    periodType: Literal["Y", "M", "Q"],
    periods: list[str] | None = None,
    objL1: str | None = None,
    objL2: str | None = None,
    itemId: str | None = None,
) -> dict[str, Any]:
    validate_config()
    return await compare_statistics(
        orgId, tableId, compareType, periodType, periods, objL1, objL2, itemId
    )


@mcp.tool(
    name="analyze_time_series",
    description=_desc("[시계열정밀] orgId+tableId+objL1+itemId 정밀 분석."),
    annotations=ANN,
)
@observe(name="analyze_time_series", as_type="tool")
async def tool_analyze_time_series(
    orgId: str,
    tableId: str,
    objL1: str,
    itemId: str,
    periodType: Literal["Y", "M", "Q"],
    objL2: str | None = None,
    yearCount: int = 10,
) -> dict[str, Any]:
    validate_config()
    return await analyze_time_series(
        orgId, tableId, objL1, itemId, periodType, objL2, yearCount
    )


@mcp.tool(
    name="get_table_info",
    description=_desc("[메타조회] 통계표 분류·항목 메타."),
    annotations=ANN,
)
@observe(name="get_table_info", as_type="tool")
async def tool_get_table_info(
    orgId: str,
    tableId: str,
    filter: str | None = None,
    sampleSize: int = 10,
) -> dict[str, Any]:
    validate_config()
    return await get_table_info(orgId, tableId, filter, sampleSize)


@mcp.tool(
    name="fetch_kosis_excel",
    description=_desc("[엑셀파싱] KOSIS 파일통계표 다운로드·마크다운 변환."),
    annotations=ANN,
)
@observe(name="fetch_kosis_excel", as_type="tool")
async def tool_fetch_kosis_excel(
    districtName: str | None = None,
    year: int | None = None,
    orgId: str | None = None,
    tblId: str | None = None,
    fileSn: int | None = None,
    keyword: str | None = None,
    listOnly: bool = False,
) -> dict[str, Any]:
    validate_config()
    return await fetch_kosis_excel(
        districtName, year, orgId, tblId, fileSn, keyword, listOnly
    )


@mcp.tool(
    name="chain_region_brief",
    description=_desc("[⛓체인] 지역 한장 종합 브리핑 — 핵심 13지표."),
    annotations=ANN,
)
@observe(name="chain_region_brief", as_type="tool")
async def tool_chain_region_brief(
    region: str,
    includeNational: bool = False,
    format: Literal["detail", "speech"] = "detail",
) -> dict[str, Any]:
    validate_config()
    return await chain_region_brief(region, includeNational, format)


@mcp.tool(
    name="chain_compare_regions",
    description=_desc("[⛓체인] N지역×M지표 비교 매트릭스."),
    annotations=ANN,
)
@observe(name="chain_compare_regions", as_type="tool")
async def tool_chain_compare_regions(
    regions: list[str], keywords: list[str]
) -> dict[str, Any]:
    validate_config()
    return await chain_compare_regions(regions, keywords)


@mcp.tool(
    name="chain_policy_indicator",
    description=_desc("[⛓체인] 정책 영역 시계열 묶음."),
    annotations=ANN,
)
@observe(name="chain_policy_indicator", as_type="tool")
async def tool_chain_policy_indicator(
    domain: Literal[
        "lowFertility", "aging", "housing", "jobs", "safety", "health", "economy"
    ],
    region: str | None = None,
    yearCount: int = 10,
) -> dict[str, Any]:
    validate_config()
    return await chain_policy_indicator(domain, region, yearCount)


@mcp.resource("kosis://categories/tree")
def resource_category_tree() -> str:
    return get_category_tree_json()


@mcp.resource("kosis://indicators/list")
def resource_key_indicators() -> str:
    return get_key_indicators_json()


@mcp.prompt(name="statistics_assistant")
def prompt_statistics_assistant(question: str) -> str:
    result = generate_statistics_assistant_prompt(question)
    return result["messages"][0]["content"]["text"]


# Ensure TOOL_COUNT stays accurate for /health
assert TOOL_COUNT == 14
