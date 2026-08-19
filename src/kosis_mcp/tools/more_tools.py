"""Remaining MCP tools: trend, rank, search, list, explain, chains."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import get_kosis_client
from kosis_mcp.config import VIEW_CODES
from kosis_mcp.data.district_file_map import DISTRICT_OPENAPI_ROUTES
from kosis_mcp.data.quick_stats_params import (
    MISLEADING_KEYWORD_HINTS,
    VITAL_STATS_TABLE_IDS,
    get_quick_stats_param,
    get_region_code,
    normalize_keyword_key,
)
from kosis_mcp.tools.quick_stats import (
    extract_district_name,
    extract_keyword,
    extract_province_name,
    format_period_with_type,
    is_within_months,
    quick_stats,
)
from kosis_mcp.utils.concurrency import CHAIN_CONCURRENCY, map_with_concurrency
from kosis_mcp.utils.data_formatter import (
    analyze_trend,
    calculate_change_rate,
    format_period,
    parse_kosis_number,
)
from kosis_mcp.utils.district_kosis_codes import get_district_kscd_candidates_for
from kosis_mcp.utils.query_parser import generate_search_terms, parse_query
from kosis_mcp.utils.regions import (
    AMBIGUOUS_DISTRICTS,
    PROVINCES,
    detect_region,
    find_province_by_district,
    normalize_province_name,
)


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
    client = get_kosis_client()
    cache = get_cache_manager()
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
            "note": hint or "search_statistics를 사용하세요.",
            "dataPoints": [],
        }

    district = extract_district_name(region or "") or extract_district_name(trimmed)
    prov = extract_province_name(trimmed, bool(district))
    region_name = "전국"
    obj_l1, obj_l2 = param.get("objL1"), param.get("objL2")
    requested = region or (find_province_by_district(district).shortName if district and find_province_by_district(district) else None) or prov
    if requested:
        code = get_region_code(param, requested)
        if code is None and param.get("regionCodes"):
            return {
                "success": False,
                "keyword": kw,
                "region": requested,
                "summary": f'"{requested}" 지역명을 인식하지 못했습니다.',
                "dataPoints": [],
            }
        if code and normalize_province_name(requested) != "전국":
            if param.get("regionObjLevel") == 2:
                obj_l2 = code
            else:
                obj_l1 = code
            region_name = normalize_province_name(requested)

    results = await cache.get_statistics_data(
        {
            "orgId": param["orgId"],
            "tableId": param["tableId"],
            "objL1": obj_l1,
            "objL2": obj_l2,
            "itemId": param["itemId"],
            "yearCount": years,
        },
        lambda: client.get_statistics_data(
            {
                "orgId": param["orgId"],
                "tblId": param["tableId"],
                "objL1": obj_l1,
                "objL2": obj_l2,
                "itmId": param["itemId"],
                "prdSe": (param.get("supportedPeriods") or ["Y"])[0],
                "newEstPrdCnt": years,
            }
        ),
    )
    points = sorted(
        [
            {
                "year": r["PRD_DE"],
                "value": parse_kosis_number(r.get("DT")),
                "formatted": r.get("DT"),
            }
            for r in results
            if parse_kosis_number(r.get("DT")) is not None
        ],
        key=lambda p: p["year"],
    )
    if len(points) < 2:
        return {
            "success": False,
            "keyword": kw,
            "region": region_name,
            "summary": "추세 분석에 충분한 데이터가 없습니다.",
            "dataPoints": [],
        }
    values = [float(p["value"]) for p in points]
    info = analyze_trend(values)
    for i in range(1, len(points)):
        ch = calculate_change_rate(values[i], values[i - 1])
        points[i]["changeRate"] = ch["formatted"]
    summary = (
        f"{region_name} {kw} {years}년 추세: {_trend_desc(info['trend'])} "
        f"(평균 변화율 {info['avgGrowthRate']:.1f}%)"
    )
    out: dict[str, Any] = {
        "success": True,
        "keyword": kw,
        "region": region_name,
        "trend": info["trend"],
        "trendDescription": _trend_desc(info["trend"]),
        "summary": summary,
        "dataPoints": [
            {
                "year": format_period(p["year"], (param.get("supportedPeriods") or ["Y"])[0]),
                "value": p["value"],
                "formatted": p["formatted"],
                **({"changeRate": p["changeRate"]} if p.get("changeRate") else {}),
            }
            for p in points
        ],
        "source": {
            "orgId": param["orgId"],
            "tableId": param["tableId"],
            "tableName": param.get("tableName"),
        },
    }
    if param.get("isProjection"):
        out["isProjection"] = True
        out["note"] = "⚠️ 장래추계 데이터입니다."
    return out


async def quick_rank(keyword: str, region: str) -> dict[str, Any]:
    client = get_kosis_client()
    cache = get_cache_manager()
    kw = extract_keyword(keyword)
    param = get_quick_stats_param(kw)
    if not param or not param.get("regionCodes"):
        return {
            "success": False,
            "answer": f'"{keyword}" 전국 순위 조회가 지원되지 않습니다.',
        }
    district = extract_district_name(region) or (
        region if re.match(r"^[가-힣]{1,4}(구|군|시)$", region.strip()) else None
    )
    route = DISTRICT_OPENAPI_ROUTES.get(kw)
    try:
        if district and route:
            # nationwide sigungu via ALL on district table when possible
            rows = await cache.get_statistics_data(
                {"rank": True, "tbl": route["tblId"], "itm": route["itmId"]},
                lambda: client.get_statistics_data(
                    {
                        "orgId": route["orgId"],
                        "tblId": route["tblId"],
                        "objL1": "ALL",
                        **({"objL2": route["objL2"]} if route.get("objL2") else {}),
                        "itmId": route["itmId"],
                        "prdSe": route.get("prdSe", "Y"),
                        "newEstPrdCnt": 2,
                    }
                ),
            )
            scope = "sigungu"
            target_name = district
        else:
            short = normalize_province_name(region)
            rows = await cache.get_statistics_data(
                {
                    "rank": True,
                    "tbl": param["tableId"],
                    "itm": param["itemId"],
                    "scope": "sido",
                },
                lambda: client.get_statistics_data(
                    {
                        "orgId": param["orgId"],
                        "tblId": param["tableId"],
                        "objL1": "ALL",
                        "objL2": param.get("objL2"),
                        "itmId": param["itemId"],
                        "prdSe": (param.get("supportedPeriods") or ["Y"])[0],
                        "newEstPrdCnt": 2,
                    }
                ),
            )
            scope = "sido"
            target_name = short

        # pick latest period
        periods = sorted({r.get("PRD_DE", "") for r in rows}, reverse=True)
        if not periods:
            return {"success": False, "answer": "순위 데이터가 없습니다."}
        latest = periods[0]
        prev = periods[1] if len(periods) > 1 else None
        cur = [
            r
            for r in rows
            if r.get("PRD_DE") == latest and parse_kosis_number(r.get("DT")) is not None
        ]
        entries = sorted(
            [
                {
                    "region": r.get("C1_NM") or r.get("C2_NM") or "",
                    "value": parse_kosis_number(r.get("DT")),
                    "formatted": r.get("DT"),
                }
                for r in cur
            ],
            key=lambda e: e["value"],
            reverse=True,
        )
        for i, e in enumerate(entries):
            e["rank"] = i + 1
        target = next(
            (
                e
                for e in entries
                if target_name in e["region"] or e["region"] in target_name
            ),
            None,
        )
        if not target:
            return {
                "success": False,
                "answer": f'"{region}" 순위 항목을 찾지 못했습니다.',
            }
        avg = sum(e["value"] for e in entries) / len(entries) if entries else None
        answer = (
            f"{target['region']} {kw}은(는) {scope} 기준 {target['rank']}위"
            f"/{len(entries)} "
            f"(값 {target['formatted']}, 평균 {avg:.2f})."
        )
        return {
            "success": True,
            "answer": answer,
            "keyword": kw,
            "region": target["region"],
            "scope": scope,
            "rank": target["rank"],
            "total": len(entries),
            "value": target["value"],
            "period": latest,
            "average": avg,
        }
    except Exception as e:
        return {"success": False, "answer": f"순위 조회 오류: {e}"}


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
        explain_rows = await cache.get_explanation(
            {"orgId": org_id, "tableId": table_id},
            lambda: client.get_statistics_explain(org_id, table_id),
        )
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


async def get_statistics_list(
    viewCode: str = "MT_ZTITLE",
    parentId: str = "",
    recommendedTopic: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    client = get_kosis_client()
    cache = get_cache_manager()
    if recommendedTopic:
        info = TOPIC_RECOMMENDATIONS.get(recommendedTopic, {"name": recommendedTopic, "description": "", "tables": []})
        recs = [
            {
                "orgId": t["ORG_ID"],
                "tableId": t["TBL_ID"],
                "tableName": t["TBL_NM"],
            }
            for t in info.get("tables", [])[:limit]
        ]
        return {
            "success": True,
            "mode": "recommended",
            "topic": {
                "code": recommendedTopic,
                "name": info.get("name"),
                "description": info.get("description"),
            },
            "recommendations": recs,
            "relatedTopics": [],
            "searchSuggestions": [],
        }
    vc = viewCode or "MT_ZTITLE"
    rows = await cache.get_statistics_list(
        {"vwCd": vc, "parentId": parentId or ""},
        lambda: client.get_statistics_list(vc, parentId or ""),
    )
    items = []
    for r in rows[:50]:
        items.append(
            {
                "listId": r.get("LIST_ID"),
                "listName": r.get("LIST_NM"),
                "orgId": r.get("ORG_ID"),
                "tableId": r.get("TBL_ID"),
                "tableName": r.get("TBL_NM"),
                "isFolder": bool(r.get("LIST_ID") and not r.get("TBL_ID")),
            }
        )
    return {
        "success": True,
        "viewName": VIEW_CODES.get(vc, vc),
        "parentId": parentId or "",
        "items": items,
        "hasMore": len(rows) > 50,
    }


async def search_statistics(
    query: str,
    orgId: str | None = None,
    sort: Literal["RANK", "DATE"] | None = "RANK",
    limit: int = 10,
) -> dict[str, Any]:
    client = get_kosis_client()
    cache = get_cache_manager()
    parsed = parse_query(query)
    terms = generate_search_terms(parsed, query) or [query]
    all_results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for term in terms[:3]:
        rows = await cache.get_search_results(
            {"q": term, "orgId": orgId, "sort": sort},
            lambda t=term: client.search_statistics(
                t, org_id=orgId, sort=sort or "RANK", result_count=limit
            ),
        )
        for r in rows:
            key = f"{r.get('ORG_ID')}:{r.get('TBL_ID')}"
            if key in seen:
                continue
            seen.add(key)
            all_results.append(
                {
                    "orgId": r.get("ORG_ID"),
                    "orgName": r.get("ORG_NM"),
                    "tableId": r.get("TBL_ID"),
                    "tableName": r.get("TBL_NM"),
                    "statName": r.get("STAT_NM"),
                    "viewCode": r.get("VW_CD"),
                }
            )
            if len(all_results) >= limit:
                break
        if len(all_results) >= limit:
            break
    return {
        "success": True,
        "query": query,
        "totalCount": len(all_results),
        "results": all_results[:limit],
        "region": detect_region(query),
    }


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


async def chain_region_brief(
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
    ok = [r for r in regional if r["success"]]
    if format == "speech":
        parts = [
            f"{r['label']} {r['value']}{r['unit'] or ''}"
            for r in ok[:5]
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
        "items": regional,
        "national": national,
    }


async def _brief_item(ind: dict[str, str], region: str | None, fetch_one) -> dict[str, Any]:
    r = await fetch_one(ind["key"], region)
    return {
        "keyword": ind["key"],
        "label": ind["label"],
        "tier": ind.get("tier"),
        "success": r.get("success"),
        "value": r.get("value"),
        "unit": r.get("unit"),
        "period": r.get("period"),
        "source": (r.get("source") or {}).get("tableName"),
        "note": r.get("note"),
        "message": (r.get("answer") or "").split("\n")[0],
    }


async def chain_compare_regions(
    regions: list[str],
    keywords: list[str],
) -> dict[str, Any]:
    regions = regions[:17]
    keywords = keywords[:8]

    async def one(pair: tuple[str, str], _i: int) -> dict[str, Any]:
        region, kw = pair
        r = await quick_stats(query=kw, region=region)
        return {
            "region": region,
            "keyword": kw,
            "success": r.get("success"),
            "value": r.get("value"),
            "unit": r.get("unit"),
            "period": r.get("period"),
            "tableId": (r.get("source") or {}).get("tableId"),
            "message": (r.get("answer") or "").split("\n")[0],
        }

    pairs = [(reg, kw) for reg in regions for kw in keywords]
    cells = await map_with_concurrency(pairs, one, CHAIN_CONCURRENCY)
    return {
        "success": True,
        "regions": regions,
        "keywords": keywords,
        "matrix": cells,
    }


async def chain_policy_indicator(
    domain: Literal[
        "lowFertility", "aging", "housing", "jobs", "safety", "health", "economy"
    ],
    region: str | None = None,
    yearCount: int = 10,
) -> dict[str, Any]:
    kws = POLICY_DOMAINS.get(domain, [])

    async def one(kw: str, _i: int) -> dict[str, Any]:
        r = await quick_trend(keyword=kw, region=region, yearCount=yearCount)
        return {
            "keyword": kw,
            "success": r.get("success"),
            "trend": r.get("trend"),
            "summary": r.get("summary"),
            "dataPoints": r.get("dataPoints"),
        }

    items = await map_with_concurrency(kws, one, CHAIN_CONCURRENCY)
    return {"success": True, "domain": domain, "region": region or "전국", "items": items}


def get_available_view_codes() -> list[dict[str, str]]:
    return [{"code": k, "name": v} for k, v in VIEW_CODES.items()]


def get_available_recommended_topics() -> list[dict[str, str]]:
    return [
        {"code": k, "name": v["name"], "description": v["description"]}
        for k, v in TOPIC_RECOMMENDATIONS.items()
    ]
