"""FastMCP server — tools, resources, prompts."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Literal

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan
from langfuse import Langfuse, observe
from langfuse.span_filter import is_default_export_span
from opentelemetry.sdk.trace import ReadableSpan

load_dotenv()

from kosis_mcp.config import SERVER_VERSION, TOOL_COUNT, validate_config
from kosis_mcp.data.quick_stats_params import QUICK_STATS_PARAMS
from kosis_mcp.prompts.statistics_assistant import (
    generate_statistics_assistant_prompt,
)
from kosis_mcp.resources.static import (
    get_category_tree_json,
    get_key_indicators_json,
)
from kosis_mcp.population_search.axes import AxisSpec
from kosis_mcp.population_search.categories import Category
from kosis_mcp.series.spec import DeriveSpec, SeriesSpec
from kosis_mcp.tools.fetch_kosis_excel import fetch_kosis_excel
from kosis_mcp.tools.get_table_info import get_table_info
from kosis_mcp.tools.more_tools import (
    browse_statistics,
    compare_regions,
    explain_statistic,
    policy_indicator,
    quick_rank,
    quick_trend,
    region_brief,
)
from kosis_mcp.tools.population_search import find_tables
from kosis_mcp.tools.quick_stats import quick_stats
from kosis_mcp.tools.series_tools import analyze_trend, compare_values
from kosis_mcp.tools.stats_query import get_statistics_data

SERVICE = "kosis-mcp"
ANN = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


def _should_export_span(span: ReadableSpan) -> bool:
    if not is_default_export_span(span):
        return False
    scope = span.instrumentation_scope
    return scope is None or scope.name != "fastmcp"


@lifespan
async def langfuse_lifecycle(_: FastMCP):
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        yield {}
        return
    langfuse = Langfuse(should_export_span=_should_export_span)
    try:
        yield {"langfuse": langfuse}
    finally:
        await asyncio.to_thread(langfuse.shutdown)


mcp = FastMCP(
    "kosis-mcp",
    version=SERVER_VERSION,
    instructions=(
        f"한국 국가데이터처 KOSIS OpenAPI 기반 MCP 서버 — {len(QUICK_STATS_PARAMS)}개 키워드, "
        "17 시도 + 자치구 230+ 라우팅. 찾기(find_tables) → 메타 → 데이터·분석, 키워드 지름길(quick_*)."
    ),
    lifespan=langfuse_lifecycle,
)


def _desc(text: str) -> str:
    return f"{SERVICE} — {text}"


@mcp.tool(
    name="find_tables",
    description=_desc(
        "[찾기] KOSIS 통계표를 찾는 기본 진입점(전 분야). 자연어 질의로 후보를 검색·메타 검증해 "
        "action(single_table/multi_table/clarify/no_exact_table), 결정된 tables[](orgId·tableId·경로·수록기간), "
        "나머지 순위 후보 candidates[]를 돌려준다. "
        "category로 29개 분야를 한정하고, axes로 분류축(by=~별로 나뉜 표, where=서울·65세 이상 같은 특정 항목값)을 지정한다. "
        "decompose=true면 '인구와 가구'처럼 여러 표 요청을 나눠 찾는다. "
        "tables[i]는 get_table_info·get_statistics_data에 그대로 넘긴다. 대표 지표 수치만 필요하면 quick_stats."
    ),
    annotations=ANN,
)
@observe(name="find_tables", as_type="tool")
async def tool_find_tables(
    query: str,
    category: Category | None = None,
    axes: list[AxisSpec] | None = None,
    timeRange: str | None = None,
    mode: Literal["auto", "fast", "thorough"] = "auto",
    decompose: bool = False,
    orgId: str | None = None,
) -> dict[str, Any]:
    validate_config()
    return await find_tables(query, category, axes, timeRange, mode, decompose, orgId)


@mcp.tool(
    name="browse_statistics",
    description=_desc(
        "[찾기·둘러보기] KOSIS 주제별 목록 트리를 탐색한다. category(29개 분야) 또는 listId로 "
        "하위 폴더·통계표를 나열한다(limit 최대 200, hasMore면 offset으로 다음 쪽). 찾을 대상이 정해져 있으면 find_tables."
    ),
    annotations=ANN,
)
@observe(name="browse_statistics", as_type="tool")
async def tool_browse_statistics(
    category: Category | None = None,
    listId: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    validate_config()
    return await browse_statistics(category, listId, limit, offset)


@mcp.tool(
    name="get_table_info",
    description=_desc(
        "[메타·코드] 통계표의 분류(objL1..)와 항목(itemId) 코드 목록을 조회한다. "
        "get_statistics_data 호출 전 코드 확인, analyze_trend·compare_values의 item·regions·filters 이름 확인용."
    ),
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
    name="explain_statistic",
    description=_desc(
        "[메타·출처] 통계의 정의·작성목적·조사방법과 인용 각주를 설명한다. 인용·출처 표기용. "
        "표의 분류·항목 코드가 필요하면 get_table_info."
    ),
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
    name="get_statistics_data",
    description=_desc(
        "[데이터] orgId+tableId로 통계표 원자료를 조회한다. regionName·itemName으로 이름 지정 가능(코드 불필요), "
        "기간(startPeriod/endPeriod) 또는 최근 N개(recentCount) 지정. 표를 모르면 find_tables, 대표 지표 수치는 quick_stats."
    ),
    annotations=ANN,
)
@observe(name="get_statistics_data", as_type="tool")
async def tool_get_statistics_data(
    orgId: str,
    tableId: str,
    periodType: Literal["Y", "H", "Q", "M", "D", "F", "IR"],
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
    name="analyze_trend",
    description=_desc(
        "[분석·추세] 시점 축 분석. series[]마다 추세·CAGR·최고/최저·최근 변화(월·분기는 전년동기 포함)를 계산하고, "
        "계열이 여러 개면 공통 구간의 증감률로 순위를 매긴다. series 항목 = find_tables의 tables[i](orgId·tableId) + "
        "item·regions·filters(이름) 또는 codes. 지정하지 않은 분류의 기본값은 tables[].appliedDefaults로 보고. "
        "같은 시점의 지역·항목 비교는 compare_values, 표 ID 없이 대표 지표 추세는 quick_trend."
    ),
    annotations=ANN,
)
@observe(name="analyze_trend", as_type="tool")
async def tool_analyze_trend(
    series: list[SeriesSpec],
    startPeriod: str | None = None,
    endPeriod: str | None = None,
    recentCount: int = 10,
) -> dict[str, Any]:
    validate_config()
    return await analyze_trend(series, startPeriod, endPeriod, recentCount)


@mcp.tool(
    name="compare_values",
    description=_desc(
        "[분석·비교] 같은 시점의 지역·항목 간 비교(순위·비중·전국 대비·차이). 표 1개(regions=\"ALL\", level=sido|sigungu)부터 "
        "여러 표(같은 지표의 다른 조사, 시도표+시군구표, 인구표÷가구표)까지 받는다. 지역은 이름으로 조인하고, "
        "주기·최신 시점이 다르면 align(common_latest|latest_each)으로 맞추며, 단위 배수(천명→명)를 정규화한다. "
        "derive=[{name, expr:\"s1/s2\"}]로 파생 지표. 키워드만 있으면 quick_rank·compare_regions, 시계열은 analyze_trend."
    ),
    annotations=ANN,
)
@observe(name="compare_values", as_type="tool")
async def tool_compare_values(
    series: list[SeriesSpec],
    period: str | None = None,
    align: Literal["common_latest", "latest_each"] = "common_latest",
    derive: list[DeriveSpec] | None = None,
    top: int | None = None,
) -> dict[str, Any]:
    validate_config()
    return await compare_values(series, period, align, derive, top)


@mcp.tool(
    name="quick_stats",
    description=_desc(
        f"[키워드·수치] 자연어 한 줄로 대표 지표({len(QUICK_STATS_PARAMS)}개 키워드)의 최신 수치를 바로 답한다. "
        "17개 시도·자치구 지원, orgId/tableId 불필요. 요청 지역 값을 못 구하면 상위 지역 값을 isFallback·fallbackRegion과 함께 준다. "
        "특정 통계표 값은 get_statistics_data, 표 탐색은 find_tables."
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
    description=_desc(
        "[키워드·추세] 키워드 하나로 대표 지표의 최근 yearCount년 추세(증감률·CAGR·최고/최저)를 보여준다(월·분기 지표는 해당 기간의 모든 시점). "
        "지역 값을 못 구하면 isFallback. 특정 표·여러 계열의 시계열 분석은 analyze_trend."
    ),
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
    description=_desc(
        "[키워드·순위] 대표 지표에서 한 지역의 순위·백분위(시도는 시도끼리, 자치구는 시군구끼리, 전국 행 제외)를 구한다. "
        "동명 자치구는 시도를 붙인다(\"부산 중구\"). 여러 지역을 나란히 비교하려면 compare_regions."
    ),
    annotations=ANN,
)
@observe(name="quick_rank", as_type="tool")
async def tool_quick_rank(keyword: str, region: str) -> dict[str, Any]:
    validate_config()
    return await quick_rank(keyword, region)


@mcp.tool(
    name="compare_regions",
    description=_desc(
        "[키워드·지역비교] 여러 지역(최대 17) × 여러 키워드(최대 8) 지표의 최신값 비교표와 키워드별 순위를 만든다. 표 ID 불필요. "
        "상위 지역 값으로 대체된 셀(isFallback)은 순위에서 뺀다. 특정 통계표(들)의 지역·항목 비교는 compare_values."
    ),
    annotations=ANN,
)
@observe(name="compare_regions", as_type="tool")
async def tool_compare_regions(
    regions: list[str], keywords: list[str]
) -> dict[str, Any]:
    validate_config()
    return await compare_regions(regions, keywords)


@mcp.tool(
    name="region_brief",
    description=_desc(
        "[키워드·브리핑] 한 지역의 핵심 13개 지표(인구·출산·고용 등)를 한 번에 요약한다. 상위 지역 참고값은 isFallback으로 표시. 지표 하나는 quick_stats."
    ),
    annotations=ANN,
)
@observe(name="region_brief", as_type="tool")
async def tool_region_brief(
    region: str,
    includeNational: bool = False,
    format: Literal["detail", "speech"] = "detail",
) -> dict[str, Any]:
    validate_config()
    return await region_brief(region, includeNational, format)


@mcp.tool(
    name="policy_indicator",
    description=_desc(
        "[키워드·정책묶음] 정책 영역(저출산·고령화·주거·일자리·안전·건강·경제)별 대표 지표 시계열을 묶어 보여준다."
    ),
    annotations=ANN,
)
@observe(name="policy_indicator", as_type="tool")
async def tool_policy_indicator(
    domain: Literal[
        "lowFertility", "aging", "housing", "jobs", "safety", "health", "economy"
    ],
    region: str | None = None,
    yearCount: int = 10,
) -> dict[str, Any]:
    validate_config()
    return await policy_indicator(domain, region, yearCount)


@mcp.tool(
    name="fetch_kosis_excel",
    description=_desc(
        "[파일] OpenAPI로 제공되지 않는 KOSIS 파일 통계표(자치구 통계연보 등)를 내려받아 마크다운 표로 변환한다. "
        "listOnly=true면 파일 목록만 돌려준다."
    ),
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
