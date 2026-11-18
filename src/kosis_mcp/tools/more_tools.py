"""Remaining MCP tools: trend, rank, browse, explain, region bundles."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import KosisApiError, get_kosis_client
from kosis_mcp.data.quick_stats_params import (
    MISLEADING_KEYWORD_HINTS,
    get_quick_stats_param,
    normalize_keyword_key,
)
from kosis_mcp.tools.quick_stats import (
    _fmt_num,
    extract_district_name,
    extract_keyword,
    extract_province_name,
    quick_stats,
)
from kosis_mcp.utils.concurrency import CHAIN_CONCURRENCY, map_with_concurrency
from kosis_mcp.utils.data_formatter import (
    calculate_change_rate,
    format_period,
    parse_kosis_number,
)
from kosis_mcp.series.fetch import fetch_spec
from kosis_mcp.series.keyword import (
    district_route,
    district_spec,
    param_spec,
    province_hint,
    resolve_region_code,
)
from kosis_mcp.series.periods import PER_YEAR
from kosis_mcp.series.metrics import rank, trend_stats
from kosis_mcp.series.resolve import is_province
from kosis_mcp.tools.series_tools import compare_values
from kosis_mcp.population_search.categories import CATEGORY_LIST_IDS
from kosis_mcp.population_search.schema import build_source
from langfuse import get_client, observe
from kosis_mcp.utils.regions import normalize_province_name


def extract_year_count(query: str) -> int | None:
    if re.search(r"민선\s*\d+\s*기", query):
        return 4
    m = re.search(r"(?:지난|최근|근래|요즘)\s*(\d+)\s*년", query) or re.search(
        r"(\d+)\s*년\s*(?:추세|추이|변화|대비|간)", query
    )
    if m:
        n = int(m.group(1))
        if 2 <= n <= 20:
            return n
    imgi = re.search(r"(?:임기|취임)\s*(\d+)\s*년", query)
    if imgi:
        n = int(imgi.group(1))
        if 1 <= n <= 20:
            return min(n + 1, 20)
    if re.search(r"(?:작년|전년)\s*(?:대비|동기)", query):
        return 2
    if re.search(r"역대|장기", query):
        return 20
    return None


def _trend_desc(trend: str) -> str:
    return {
        "increasing": "지속적인 상승 추세를 보이고 있습니다.",
        "decreasing": "지속적인 하락 추세를 보이고 있습니다.",
        "stable": "안정적인 흐름을 유지하고 있습니다.",
        "fluctuating": "변동이 큰 불안정한 흐름을 보이고 있습니다.",
    }.get(trend, "추세를 파악하기 어렵습니다.")


async def quick_trend(
    keyword: str,
    region: str | None = None,
    yearCount: int | None = None,
) -> dict[str, Any]:
    trimmed = (keyword or "").strip()
    if not trimmed:
        return {"success": False, "summary": "키워드를 입력하세요.", "dataPoints": []}
    years = yearCount or extract_year_count(trimmed) or 10
    kw = extract_keyword(trimmed)
    param = get_quick_stats_param(kw)
    if not param:
        norm = normalize_keyword_key(trimmed)
        hint = next(
            (h["hint"] for h in MISLEADING_KEYWORD_HINTS if h["pattern"].search(norm)),
            None,
        )
        return {
            "success": False,
            "keyword": kw,
            "region": region or "전국",
            "summary": f'"{keyword}" 추세 조회 미지원.',
            "note": hint or "find_tables로 통계표를 찾으세요.",
            "dataPoints": [],
        }

    district = extract_district_name(region or "") or extract_district_name(trimmed)
    prov_q = extract_province_name(region or "", False) or extract_province_name(trimmed, False)
    route = district_route(kw)
    spec = None
    note: str | None = None
    fallback_region: str | None = None
    source = {"orgId": param["orgId"], "tableId": param["tableId"], "tableName": param.get("tableName")}
    region_name = "전국"
    if district and route:
        try:
            spec = await district_spec(route, district, province=prov_q)
        except Exception:
            spec = None
        if spec:
            region_name = district
            source = {"orgId": route["orgId"], "tableId": route["tblId"], "tableName": route.get("description")}
    if spec is None:
        prov = province_hint(district, prov_q) if district else None
        requested = (region if region and not district else None) or (prov.shortName if prov else None) or (
            None if district else extract_province_name(trimmed, False)
        )
        spec, region_name = param_spec(param, region=requested)
        if spec is None and param.get("regionCodes"):
            live = await resolve_region_code(
                param["orgId"], param["tableId"], requested or "",
                obj_l=2 if param.get("regionObjLevel") == 2 else None,
            )
            if live:
                spec, region_name = param_spec(param, region=requested, region_code=live)
        if spec is None:
            # 성공은 유지하되 전국 값임을 플래그로 명시한다.
            spec, region_name = param_spec(param)
            fallback_region = "전국"
            note = (
                f'"{requested}" 지역 값은 이 지표에서 조회할 수 없어 전국 추세를 표시합니다.'
                if param.get("regionCodes")
                else f'"{kw}" 통계는 지역별 조회를 지원하지 않아 전국 추세를 표시합니다.'
            )
        elif district:
            fallback_region = region_name
            note = f'"{district}" 자치구 추세는 지원되지 않아 {region_name} 값을 표시합니다.'

    period_type = spec.get("periodType") or "Y"
    # yearCount는 연 단위: 월·분기·반기 주기는 연간 시점 수를 곱한다.
    points_wanted = years * PER_YEAR.get(period_type, 1)
    try:
        res = await fetch_spec(spec, recent=points_wanted)
    except KosisApiError as e:
        return {"success": False, "keyword": kw, "region": region_name, "summary": f"조회 오류: {e}", "dataPoints": []}
    series = next((s for s in res["series"] if any(p["value"] is not None for p in s["points"])), None)
    points = [p for p in (series or {}).get("points", []) if p["value"] is not None]
    if len(points) < 2:
        return {
            "success": False,
            "keyword": kw,
            "region": region_name,
            "summary": "추세 분석에 충분한 데이터가 없습니다.",
            "dataPoints": [],
        }
    stats = trend_stats(points, period_type)
    data_points = []
    for i, p in enumerate(points):
        dp: dict[str, Any] = {
            "year": format_period(p["period"], period_type),
            "period": p["period"],
            "value": p["value"],
            "formatted": _fmt_num(str(p["raw"])),
        }
        if i:
            dp["changeRate"] = calculate_change_rate(p["value"], points[i - 1]["value"])["formatted"]
        data_points.append(dp)
    summary = (
        f"{region_name} {kw} {years}년({len(points)}개 시점) 추세: {_trend_desc(stats['trend'])} "
        f"(평균 변화율 {stats['avgGrowthRate']:.1f}%)"
    )
    out: dict[str, Any] = {
        "success": True,
        "keyword": kw,
        "region": region_name,
        "trend": stats["trend"],
        "trendDescription": _trend_desc(stats["trend"]),
        "summary": summary,
        "cagr": stats.get("cagr"),
        "periodType": period_type,
        "unit": (series.get("unit") if series else None) or param.get("unit"),
        "dataPoints": data_points,
        "source": source,
    }
    if fallback_region:
        out["isFallback"] = True
        out["fallbackRegion"] = fallback_region
        out["requestedRegion"] = district or region
    notes = [n for n in (note, "⚠️ 장래추계 데이터입니다." if param.get("isProjection") else None) if n]
    if param.get("isProjection"):
        out["isProjection"] = True
    if notes:
        out["note"] = " ".join(notes)
    return out


async def quick_rank(keyword: str, region: str) -> dict[str, Any]:
    kw = extract_keyword(keyword)
    param = get_quick_stats_param(kw)
    if not param or not param.get("regionCodes"):
        out: dict[str, Any] = {
            "success": False,
            "answer": f'"{keyword}" 전국 순위 조회가 지원되지 않습니다.',
        }
        if param:
            out["source"] = build_source(
                param["orgId"], param["tableId"], param.get("tableName") or ""
            )
        return out
    district = extract_district_name(region) or (
        region.strip()
        if re.match(r"^[가-힣]{1,4}(구|군|시)$", region.strip()) and not is_province(region)
        else None
    )
    prov_q = extract_province_name(region, False)
    route = district_route(kw)
    if district and route:
        spec = await district_spec(route, district, all_regions=True)
        scope = "sigungu"
        tbl_org, tbl_id = route["orgId"], route["tblId"]
    else:
        spec, _ = param_spec(param, all_regions=True)
        scope = "sido"
        tbl_org, tbl_id = param["orgId"], param["tableId"]
    source = build_source(tbl_org, tbl_id, param.get("tableName") or "")
    if spec is None:
        return {"success": False, "answer": "순위 데이터가 없습니다.", "source": source}
    spec = {**spec, "level": scope, "label": "value"}  # type: ignore[typeddict-item]
    try:
        cmp = await compare_values([spec])
    except Exception as e:
        return {"success": False, "answer": f"순위 조회 오류: {e}", "source": source}
    if not cmp.get("success"):
        return {"success": False, "answer": cmp.get("error") or "순위 데이터가 없습니다.", "source": source}

    ranked = [r for r in cmp["rows"] if "value" in (r.get("ranks") or {})]
    if scope == "sido":
        short = normalize_province_name(region)
        matches = [r for r in ranked if r["key"] == short]
    else:
        prov_short = normalize_province_name(prov_q) if prov_q else None
        matches = [
            r
            for r in ranked
            if (r["key"] == f"{prov_short} {district}" if prov_short else (r["key"] == district or r["key"].endswith(f" {district}")))
        ]
    if len(matches) != 1:
        out = {
            "success": False,
            "answer": (
                f'"{region}"이(가) 여러 지역과 일치합니다. 시도를 붙여 주세요: {[r["key"] for r in matches]}'
                if matches
                else f'"{region}" 순위 항목을 찾지 못했습니다. '
                f"(기준 시점 {(cmp['columns'][0].get('period') if cmp.get('columns') else '') or ''} 순위표에 없음 — "
                "신설·개편 지역은 아직 연간 값이 없을 수 있습니다.)"
            ),
            "source": source,
        }
        return out
    target = matches[0]
    cell = target["values"]["value"]
    values = [r["values"]["value"]["value"] for r in ranked]
    avg = sum(values) / len(values) if values else None
    unit = cell.get("unit") or ""
    answer = (
        f"{target['key']} {kw}은(는) {scope} 기준 {target['ranks']['value']}위/{len(ranked)} "
        f"(값 {cell['value']:,.10g}{unit}, 평균 {avg:,.2f})."
    )
    out = {
        "success": True,
        "answer": answer,
        "keyword": kw,
        "region": target["key"],
        "scope": scope,
        "rank": target["ranks"]["value"],
        "total": len(ranked),
        "percentile": round((len(ranked) - target["ranks"]["value"]) / (len(ranked) - 1) * 100, 1)
        if len(ranked) > 1
        else None,
        "value": cell["value"],
        "unit": unit,
        "period": cell["period"],
        "average": avg,
        "source": source,
    }
    if cmp.get("warnings"):
        out["warnings"] = cmp["warnings"]
    return out


async def explain_statistic(
    keyword: str | None = None,
    orgId: str | None = None,
    tableId: str | None = None,
) -> dict[str, Any]:
    client = get_kosis_client()
    cache = get_cache_manager()
    org_id = (orgId or "").strip() or None
    table_id = (tableId or "").strip() or None
    table_name_hint = None
    if (not org_id or not table_id) and keyword:
        kw = extract_keyword(keyword.strip())
        param = get_quick_stats_param(kw)
        if param:
            org_id = org_id or param["orgId"]
            table_id = table_id or param["tableId"]
            table_name_hint = param.get("tableName")
    if not org_id or not table_id:
        return {
            "success": False,
            "answer": "orgId+tableId 또는 지원 keyword가 필요합니다.",
        }
    try:
        try:
            explain_rows = await cache.get_explanation(
                {"orgId": org_id, "tableId": table_id},
                lambda: client.get_statistics_explain(org_id, table_id),
            )
        except KosisApiError as e:
            # 통계설명 미등록 표는 KOSIS가 '데이터 없음' 오류로 답한다 → 인용문구만 제공.
            if _NO_DATA_MARK not in str(e):
                raise
            explain_rows = []
        tbl_meta = await cache.get_table_meta(
            {"orgId": org_id, "tableId": table_id, "type": "TBL"},
            lambda: client.get_table_meta(org_id, table_id, "TBL"),
        )
        explain: dict[str, str] = {}
        for row in explain_rows:
            if isinstance(row, dict):
                explain.update({k: str(v) for k, v in row.items() if v})
        tbl = tbl_meta[0] if tbl_meta else {}
        table_name = tbl.get("TBL_NM") or table_name_hint or table_id
        org_name = tbl.get("ORG_NM") or ("국가데이터처" if org_id == "101" else f"기관 {org_id}")
        today = datetime.now().date().isoformat()
        citation = (
            f"출처: {org_name}"
            + (f", 「{explain.get('statsNm')}」" if explain.get("statsNm") else "")
            + f", {table_name} (KOSIS, 통계표 ID: {table_id}), {today} 추출."
        )
        labels = [
            ("statsNm", "통계조사명"),
            ("writingPurps", "작성목적"),
            ("examinPd", "조사주기"),
            ("mainTermExpl", "주요 용어해설"),
            ("dataUserNote", "이용 시 유의사항"),
        ]
        body = []
        explanation = {}
        for key, label in labels:
            v = (explain.get(key) or "").strip()
            if v:
                explanation[label] = v
                body.append(f"• {label}: {v}")
        answer = (
            f"📚 {table_name} ({org_name}, KOSIS {table_id})\n\n"
            + ("\n".join(body) if body else "통계설명 자료 미등록 — 인용문구만 제공.")
            + f"\n\n📎 인용 각주:\n{citation}"
        )
        return {
            "success": True,
            "answer": answer,
            "citation": citation,
            **({"explanation": explanation} if explanation else {}),
            "source": {
                "orgId": org_id,
                "tableId": table_id,
                "tableName": table_name,
                "retrievedAt": today,
            },
        }
    except Exception as e:
        return {"success": False, "answer": f"통계설명 조회 중 오류: {e}"}


TOPIC_RECOMMENDATIONS: dict[str, dict[str, Any]] = {
    "population": {
        "name": "인구",
        "description": "인구·출산·고령",
        "tables": [
            {"ORG_ID": "101", "TBL_ID": "DT_1B040A3", "TBL_NM": "주민등록인구"},
            {"ORG_ID": "101", "TBL_ID": "DT_1B81A17", "TBL_NM": "합계출산율"},
        ],
    },
    "economy": {
        "name": "경제",
        "description": "GDP·물가·무역",
        "tables": [
            {"ORG_ID": "101", "TBL_ID": "DT_2AS004", "TBL_NM": "국내총생산"},
        ],
    },
    "employment": {
        "name": "고용",
        "description": "실업·고용",
        "tables": [
            {"ORG_ID": "101", "TBL_ID": "DT_1DA7102S", "TBL_NM": "실업률"},
        ],
    },
    "housing": {"name": "주거", "description": "주택·아파트", "tables": []},
    "education": {"name": "교육", "description": "교육", "tables": []},
    "health": {"name": "보건", "description": "의료", "tables": []},
    "environment": {"name": "환경", "description": "환경", "tables": []},
    "transport": {"name": "교통", "description": "교통", "tables": []},
    "social": {"name": "사회", "description": "사회", "tables": []},
}


# 분야 → 기존 추천 카드 (Phase 3에서 대표 조사로 교체)
_CATEGORY_TOPICS = {"인구": "population", "국민계정": "economy", "노동": "employment"}


BROWSE_MAX_LIMIT = 200


async def browse_statistics(
    category: str | None = None,
    listId: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    client = get_kosis_client()
    cache = get_cache_manager()
    limit = min(max(1, limit), BROWSE_MAX_LIMIT)
    offset = max(0, offset)
    parent = listId or (CATEGORY_LIST_IDS.get(category, "") if category else "")
    rows = await cache.get_statistics_list(
        {"vwCd": "MT_ZTITLE", "parentId": parent},
        lambda: client.get_statistics_list("MT_ZTITLE", parent),
    )
    items = []
    for r in rows[offset : offset + limit]:
        is_folder = bool(r.get("LIST_ID") and not r.get("TBL_ID"))
        item = {
            "name": r.get("LIST_NM") if is_folder else r.get("TBL_NM"),
            "isFolder": is_folder,
        }
        if is_folder:
            item["listId"] = r.get("LIST_ID")
        else:
            item.update(
                {
                    "orgId": r.get("ORG_ID"),
                    "tableId": r.get("TBL_ID"),
                    "tableName": r.get("TBL_NM"),
                    "statId": r.get("STAT_ID"),
                    "lastUpdated": r.get("SEND_DE"),
                }
            )
        items.append(item)
    out: dict[str, Any] = {
        "success": True,
        "category": None if listId else category,
        "listId": parent,
        "items": items,
        "offset": offset,
        "total": len(rows),
        "hasMore": len(rows) > offset + limit,
    }
    topic = TOPIC_RECOMMENDATIONS.get(_CATEGORY_TOPICS.get(category or "", ""))
    if topic and not listId:
        out["recommendations"] = [
            {"orgId": t["ORG_ID"], "tableId": t["TBL_ID"], "tableName": t["TBL_NM"]}
            for t in topic["tables"]
        ]
    return out


# KOSIS answers an empty search with an error instead of [].
_NO_DATA_MARK = "데이터가 존재하지 않습니다"


SEARCH_PER_TERM = 20


def _search_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "orgId": r.get("ORG_ID"),
        "orgName": r.get("ORG_NM"),
        "tableId": r.get("TBL_ID"),
        "tableName": r.get("TBL_NM"),
        "statName": r.get("STAT_NM"),
        "statId": r.get("STAT_ID"),
        "viewCode": r.get("VW_CD"),
        "path": r.get("MT_ATITLE"),
        "pathId": r.get("FULL_PATH_ID"),
        "startPeriod": r.get("STRT_PRD_DE"),
        "endPeriod": r.get("END_PRD_DE"),
        "searchRank": None,
    }


@observe(name="search.merge", as_type="span")
async def _merge_search_results(
    cache: Any,
    client: Any,
    terms: list[str],
    orgId: str | None,
    sort: Literal["RANK", "DATE"] | None,
    limit: int,
    parsed: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """검색어마다 SEARCH_PER_TERM건을 받아 순위대로 번갈아 합친다(첫 검색어가 limit을 독점하지 않도록).
    각 행의 searchRank는 그 표가 처음 나온 검색어 안의 순위(0부터)."""
    per_term: list[dict[str, Any]] = []
    lists: list[list[dict[str, Any]]] = []
    count = max(limit, SEARCH_PER_TERM)
    for term in terms[:4]:
        params = {"q": term, "orgId": orgId, "sort": sort, "count": count}
        cache_key = cache._generate_key("search", params)
        cache_hit = (await cache._get(cache_key)) is not None
        try:
            rows = await cache.get_search_results(
                params,
                lambda t=term: client.search_statistics(
                    t, org_id=orgId, sort=sort or "RANK", result_count=count
                ),
            )
        except KosisApiError as e:
            if _NO_DATA_MARK not in str(e):
                raise
            rows = []
        lists.append(rows)
        per_term.append(
            {
                "term": term,
                "table_ids": [r.get("TBL_ID") for r in rows if r.get("TBL_ID")][:limit],
                "count": len(rows),
                "cache_hit": cache_hit,
            }
        )
    all_results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i in range(count):
        for rows in lists:
            if i >= len(rows) or not rows[i].get("TBL_ID"):
                continue
            key = f"{rows[i].get('ORG_ID')}:{rows[i].get('TBL_ID')}"
            if key in seen:
                continue
            seen.add(key)
            row = _search_row(rows[i])
            row["searchRank"] = i
            all_results.append(row)
        if len(all_results) >= limit:
            break
    all_results = all_results[:limit]
    merged_table_ids = [r["tableId"] for r in all_results]
    get_client().update_current_span(
        metadata={
            "parsed": {
                k: parsed[k]
                for k in ("topics", "regions", "keywords", "timeRange", "intent")
                if k in parsed
            },
            "terms": terms,
            "per_term": per_term,
            "merged_table_ids": merged_table_ids,
        }
    )
    return all_results, per_term


REGION_BRIEF_INDICATORS = [
    {"key": "인구", "label": "주민등록 인구", "tier": "core"},
    {"key": "출산율", "label": "합계출산율", "tier": "core"},
    {"key": "고령인구", "label": "65세 이상 고령인구", "tier": "core"},
    {"key": "실업률", "label": "실업률", "tier": "core"},
    {"key": "고용률", "label": "고용률", "tier": "core"},
    {"key": "GRDP", "label": "지역내총생산(명목)", "tier": "econ"},
    {"key": "월급", "label": "월평균 임금", "tier": "econ"},
    {"key": "아파트가격", "label": "아파트매매가격지수", "tier": "housing"},
    {"key": "전세가격", "label": "주택전세가격지수", "tier": "housing"},
    {"key": "의사수", "label": "인구 천명당 의사수", "tier": "social"},
    {"key": "교통사고", "label": "자동차 천대당 교통사고", "tier": "social"},
    {"key": "범죄율", "label": "인구 천명당 범죄발생", "tier": "social"},
    {"key": "미세먼지", "label": "PM2.5 농도", "tier": "env"},
]

POLICY_DOMAINS: dict[str, list[str]] = {
    "lowFertility": ["출산율", "출생아수", "혼인건수", "평균초혼연령"],
    "aging": ["고령인구", "노령화지수", "기대수명"],
    "housing": ["아파트가격", "전세가격", "주택매매가격"],
    "jobs": ["실업률", "고용률", "취업자수", "월급"],
    "safety": ["범죄율", "교통사고"],
    "health": ["의사수", "미세먼지"],
    "economy": ["GDP", "경제성장률", "물가", "GRDP"],
}


async def region_brief(
    region: str,
    includeNational: bool = False,
    format: Literal["detail", "speech"] = "detail",
) -> dict[str, Any]:
    async def fetch_one(kw: str, region_arg: str | None = None):
        try:
            return await quick_stats(query=kw, region=region_arg)
        except Exception as e:
            return {"success": False, "answer": f"조회 실패: {e}"}

    regional = await map_with_concurrency(
        REGION_BRIEF_INDICATORS,
        lambda ind, _i: _brief_item(ind, region, fetch_one),
        CHAIN_CONCURRENCY,
    )
    national = None
    if includeNational:
        national = await map_with_concurrency(
            REGION_BRIEF_INDICATORS,
            lambda ind, _i: _brief_item(ind, None, fetch_one),
            CHAIN_CONCURRENCY,
        )
    ok = [r for r in regional if r["success"] and not r.get("isFallback")]
    fallbacks = [r for r in regional if r["success"] and r.get("isFallback")]
    if format == "speech":
        parts = [
            f"{r['label']} {r['value']}{r['unit'] or ''}"
            + (f"({r['fallbackRegion']} 기준 참고값)" if r.get("isFallback") else "")
            for r in [x for x in regional if x["success"]][:5]
            if r.get("value") is not None
        ]
        speech = f"{region} — " + ", ".join(parts) if parts else f"{region} 핵심 통계 조회 실패"
        return {
            "success": True,
            "region": region,
            "format": "speech",
            "speech": speech,
            "items": regional,
        }
    return {
        "success": True,
        "region": region,
        "format": "detail",
        "successCount": len(ok),
        "fallbackCount": len(fallbacks),
        "items": regional,
        "national": national,
    }


async def _brief_item(ind: dict[str, str], region: str | None, fetch_one) -> dict[str, Any]:
    r = await fetch_one(ind["key"], region)
    src = r.get("source") or {}
    return {
        "keyword": ind["key"],
        "label": ind["label"],
        "tier": ind.get("tier"),
        "success": r.get("success"),
        "value": r.get("value"),
        "unit": r.get("unit"),
        "period": r.get("period"),
        "source": src if src.get("tableId") else None,
        "note": r.get("note"),
        "isFallback": bool(r.get("isFallback")),
        "fallbackRegion": r.get("fallbackRegion"),
        "message": (r.get("answer") or r.get("summary") or "").split("\n")[0],
    }


COMPARE_MAX_REGIONS, COMPARE_MAX_KEYWORDS = 17, 8


async def compare_regions(
    regions: list[str],
    keywords: list[str],
) -> dict[str, Any]:
    warnings: list[str] = []
    if len(regions) > COMPARE_MAX_REGIONS or len(keywords) > COMPARE_MAX_KEYWORDS:
        warnings.append(
            f"지역 {COMPARE_MAX_REGIONS}개·키워드 {COMPARE_MAX_KEYWORDS}개까지만 비교했습니다 "
            f"(요청: 지역 {len(regions)}개, 키워드 {len(keywords)}개)."
        )
    regions = regions[:COMPARE_MAX_REGIONS]
    keywords = keywords[:COMPARE_MAX_KEYWORDS]

    async def one(pair: tuple[str, str], _i: int) -> dict[str, Any]:
        region, kw = pair
        try:
            r = await quick_stats(query=kw, region=region)
        except Exception as e:
            r = {"success": False, "answer": f"조회 실패: {e}"}
        src = r.get("source") or {}
        value = r.get("value")
        return {
            "region": region,
            "keyword": kw,
            "success": r.get("success"),
            "value": value,
            "numericValue": parse_kosis_number(str(value)) if value is not None else None,
            "unit": r.get("unit"),
            "period": r.get("period"),
            "isFallback": bool(r.get("isFallback")),
            "fallbackRegion": r.get("fallbackRegion"),
            "note": r.get("note"),
            "source": src if src.get("tableId") else None,
            "message": (r.get("answer") or "").split("\n")[0],
        }

    pairs = [(reg, kw) for reg in regions for kw in keywords]
    cells = await map_with_concurrency(pairs, one, CHAIN_CONCURRENCY)
    ranks: dict[str, list[dict[str, Any]]] = {}
    for kw in keywords:
        # 상위 지역 값으로 대체된 셀(isFallback)은 순위에서 뺀다.
        kw_cells = [c for c in cells if c["keyword"] == kw and c["success"] and not c["isFallback"]]
        order = rank({c["region"]: c["numericValue"] for c in kw_cells})
        ranks[kw] = sorted(
            (
                {"region": c["region"], "value": c["numericValue"], "period": c.get("period"), "rank": order[c["region"]]}
                for c in kw_cells
                if c["region"] in order
            ),
            key=lambda x: x["rank"],
        )
        periods = {c.get("period") for c in kw_cells if c.get("numericValue") is not None}
        if len(periods) > 1:
            warnings.append(f"'{kw}' 시점이 지역마다 다릅니다: {sorted(p for p in periods if p)} (순위는 참고용)")
    fallback_cells = [f"{c['region']}·{c['keyword']}" for c in cells if c["isFallback"]]
    if fallback_cells:
        warnings.append(f"상위 지역 값으로 대체되어 순위에서 뺀 셀: {fallback_cells}")
    failed = [c for c in cells if not c["success"]]
    out: dict[str, Any] = {
        "success": len(failed) < len(cells),
        "regions": regions,
        "keywords": keywords,
        "matrix": cells,
        "ranks": ranks,
        "failedCount": len(failed),
    }
    if warnings:
        out["warnings"] = warnings
    return out


async def policy_indicator(
    domain: Literal[
        "lowFertility", "aging", "housing", "jobs", "safety", "health", "economy"
    ],
    region: str | None = None,
    yearCount: int = 10,
) -> dict[str, Any]:
    kws = POLICY_DOMAINS.get(domain, [])

    async def one(kw: str, _i: int) -> dict[str, Any]:
        try:
            r = await quick_trend(keyword=kw, region=region, yearCount=yearCount)
        except Exception as e:
            r = {"success": False, "summary": f"조회 실패: {e}"}
        return {
            "keyword": kw,
            "success": r.get("success"),
            "trend": r.get("trend"),
            "summary": r.get("summary"),
            "periodType": r.get("periodType"),
            "unit": r.get("unit"),
            "isFallback": bool(r.get("isFallback")),
            "fallbackRegion": r.get("fallbackRegion"),
            "dataPoints": r.get("dataPoints"),
            "source": r.get("source"),
        }

    items = await map_with_concurrency(kws, one, CHAIN_CONCURRENCY)
    failed = sum(1 for i in items if not i["success"])
    return {
        "success": failed < len(items),
        "domain": domain,
        "region": region or "전국",
        "failedCount": failed,
        "fallbackCount": sum(1 for i in items if i["isFallback"]),
        "items": items,
    }
