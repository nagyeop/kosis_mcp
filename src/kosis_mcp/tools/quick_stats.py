"""quick_stats — natural language → KOSIS value."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import get_kosis_client
from kosis_mcp.data.district_file_map import (
    DISTRICT_KEYWORD_TO_FILESN,
    DISTRICT_OPENAPI_ROUTES,
    extract_district_highlight,
)
from kosis_mcp.data.quick_stats_params import (
    KEYWORD_ALIASES,
    KEYWORD_LOOKUP,
    MISLEADING_KEYWORD_HINTS,
    QUICK_STATS_PARAMS,
    VITAL_STATS_TABLE_IDS,
    get_quick_stats_param,
    get_region_code,
    normalize_keyword_key,
)
from kosis_mcp.utils.data_formatter import parse_kosis_number
from kosis_mcp.utils.district_kosis_codes import get_district_kscd_candidates_for
from kosis_mcp.utils.regions import (
    AMBIGUOUS_DISTRICTS,
    PROVINCE_NAME_VARIANTS,
    PROVINCES,
    find_province_by_district,
    normalize_province_name,
)

NON_DISTRICT_WORDS = {
    "인구",
    "총인구",
    "수입",
    "수출",
    "집값",
    "월급",
    "취업",
    "주가",
    "노인구",
    "고령인구",
    "65세이상인구",
}

PROVINCE_SHORT_NAMES = [p.shortName for p in PROVINCES]
PROVINCE_FULL_NAMES = [p.fullName for p in PROVINCES]

SORTED_NORM_KEYS = sorted(
    (k for k in KEYWORD_LOOKUP if len(k) >= 2), key=len, reverse=True
)


def is_allowed_keyword_prefix(prefix: str) -> bool:
    if not prefix:
        return True
    p = prefix[:-1] if prefix.endswith("의") else prefix
    if not p:
        return True
    last = p[-1]
    if not re.search(r"[가-힣]", last):
        return True
    if re.search(r"(시|도|구|군|읍|면|동|월|분기)$", p):
        return True
    if re.search(r"(\d년|작년|전년|금년|올해)$", p):
        return True
    if re.search(r"(전국|한국|대한민국|우리나라|국내)$", p):
        return True
    for name in PROVINCE_SHORT_NAMES:
        if p.endswith(name):
            return True
    return False


def extract_keyword(query: str) -> str:
    if not query:
        return query
    norm_query = normalize_keyword_key(query)
    if not norm_query:
        return query
    for nk in SORTED_NORM_KEYS:
        idx = norm_query.find(nk)
        while idx != -1:
            if is_allowed_keyword_prefix(norm_query[:idx]):
                return KEYWORD_LOOKUP[nk]
            idx = norm_query.find(nk, idx + 1)
    return query


def extract_province_name(query: str, district_detected: bool) -> str | None:
    if district_detected:
        return None
    for item in PROVINCE_NAME_VARIANTS:
        if item["name"] in query:
            return item["short"]
    for name in PROVINCE_SHORT_NAMES:
        idx = query.find(name)
        if idx == -1:
            continue
        after = query[idx + len(name)] if idx + len(name) < len(query) else ""
        if after in ("구", "시", "군", "도"):
            continue
        return name
    return None


def extract_district_name(query: str) -> str | None:
    for token in re.split(r"\s+", query):
        if not re.match(r"^[가-힣]{1,4}(구|군|시)$", token):
            continue
        if token in PROVINCE_FULL_NAMES or token in PROVINCE_SHORT_NAMES:
            continue
        if token in NON_DISTRICT_WORDS:
            continue
        if token in QUICK_STATS_PARAMS or token in KEYWORD_ALIASES:
            continue
        return token
    return None


def format_period_with_type(period: str, period_type: str) -> str:
    if len(period) == 4:
        return f"{period}년"
    if len(period) == 6:
        year = period[:4]
        num = int(period[4:])
        if period_type == "Q":
            return f"{year}년 {num}분기"
        if period_type == "M":
            return f"{year}년 {num}월"
        if period_type == "S":
            return f"{year}년 {'상' if num == 1 else '하'}반기"
    return period


def is_within_months(period: str, months: int) -> bool:
    try:
        year = int(period[:4])
    except ValueError:
        return False
    month = int(period[4:6]) if len(period) >= 6 else 12
    now = datetime.now()
    months_ago = (now.year - year) * 12 + (now.month - month)
    return months_ago <= months


def get_korean_particle(text: str) -> str:
    if not text:
        return "은"
    code = ord(text[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return "은" if (code - 0xAC00) % 28 != 0 else "는"
    return "는"


def _fmt_num(value: str) -> str:
    if "," in value:
        return value
    try:
        n = float(value)
        if n == int(n):
            return f"{int(n):,}"
        return f"{n:,}"
    except ValueError:
        return value


def generate_natural_response(
    *,
    region_name: str,
    value: str,
    unit: str,
    period: str,
    description: str,
) -> str:
    formatted_value = _fmt_num(value)
    formatted_unit = unit
    if "=" in unit:
        formatted_unit = unit if unit.startswith("(") else f" ({unit})"
    suffix = get_korean_particle(description)
    if region_name == "전국":
        return f"{period} 한국의 {description}{suffix} {formatted_value}{formatted_unit}입니다."
    return f"{period} {region_name}의 {description}{suffix} {formatted_value}{formatted_unit}입니다."


async def quick_stats(
    query: str,
    region: str | None = None,
    year: int | None = None,
    period: str | None = None,
    month: int | None = None,
    quarter: int | None = None,
) -> dict[str, Any]:
    from kosis_mcp.tools.fetch_kosis_excel import fetch_kosis_excel

    client = get_kosis_client()
    cache = get_cache_manager()
    try:
        trimmed_query = (query or "").strip()
        if not trimmed_query:
            return {
                "success": False,
                "answer": "조회할 통계 키워드를 입력해주세요.",
                "note": '예: "인구", "실업률", "GDP", "서울 아파트가격".',
            }
        keyword = extract_keyword(trimmed_query)
        param = get_quick_stats_param(keyword)
        if not param:
            guide = (
                "📊 지원 키워드: 인구, 출산율, 실업률, 고용률, GDP, GRDP, 물가, "
                "아파트가격, 전세가격, 미세먼지, 교통사고, 의사수, 범죄율 등 92개"
            )
            norm_q = normalize_keyword_key(trimmed_query)
            misleading = next(
                (h["hint"] for h in MISLEADING_KEYWORD_HINTS if h["pattern"].search(norm_q)),
                None,
            )
            return {
                "success": False,
                "answer": f'"{query}"에 대한 빠른 조회가 지원되지 않습니다.',
                "note": (f"{misleading}\n\n" if misleading else "")
                + f'{guide}\n\n🔍 search_statistics("{query}")로 검색해보세요.',
            }

        region_name = "전국"
        obj_l1 = param.get("objL1")
        obj_l2 = param.get("objL2")
        requested_region: str | None = None
        district_note: str | None = None

        trimmed_region = (region or "").strip()
        district_from_region = (
            extract_district_name(trimmed_region) if trimmed_region else None
        )
        district_from_query = (
            None if district_from_region else extract_district_name(trimmed_query)
        )
        district_name = district_from_region or district_from_query
        prov_from_query = extract_province_name(trimmed_query, False)

        if district_name:
            prov = find_province_by_district(district_name)
            if (
                prov_from_query
                and district_name in AMBIGUOUS_DISTRICTS
                and prov_from_query in AMBIGUOUS_DISTRICTS[district_name]
            ):
                cand = next((p for p in PROVINCES if p.shortName == prov_from_query), None)
                if cand:
                    prov = cand
            if prov:
                requested_region = prov.shortName
                district_note = (
                    f'💡 "{district_name}" 자치구 데이터는 우선 OpenAPI/엑셀 경로로 조회합니다. '
                    f"실패 시 {prov.shortName} 광역값을 참고로만 표시합니다."
                )
            elif prov_from_query:
                requested_region = prov_from_query
                district_note = (
                    f'💡 "{district_name}" 매핑이 모호합니다. {prov_from_query} 데이터로 표시합니다.'
                )
            else:
                district_note = (
                    f'💡 "{district_name}" 매핑이 모호합니다. 전국 데이터로 표시합니다.'
                )
        elif trimmed_region:
            requested_region = trimmed_region
        elif prov_from_query:
            requested_region = prov_from_query

        route = DISTRICT_OPENAPI_ROUTES.get(keyword)
        if district_name and route:
            try:
                prov_hint = find_province_by_district(district_name)
                if (
                    prov_from_query
                    and district_name in AMBIGUOUS_DISTRICTS
                    and prov_from_query in AMBIGUOUS_DISTRICTS[district_name]
                ):
                    cand = next(
                        (p for p in PROVINCES if p.shortName == prov_from_query), None
                    )
                    if cand:
                        prov_hint = cand
                district_codes = await get_district_kscd_candidates_for(
                    route["orgId"],
                    route["tblId"],
                    district_name,
                    prov_hint,
                    route.get("objId") or "auto",
                )
                start_prd = end_prd = None
                if year:
                    y = str(year)
                    prd_se = route.get("prdSe", "Y")
                    if prd_se == "Y":
                        start_prd = end_prd = y
                    elif prd_se == "M":
                        start_prd = f"{y}{month:02d}" if month else f"{y}01"
                        end_prd = f"{y}{month:02d}" if month else f"{y}12"
                    elif prd_se == "Q":
                        start_prd = f"{y}{quarter:02d}" if quarter else f"{y}01"
                        end_prd = f"{y}{quarter:02d}" if quarter else f"{y}04"
                    elif prd_se == "S":
                        start_prd, end_prd = f"{y}01", f"{y}02"

                for district_code in district_codes:
                    obj_l1_final = (
                        route.get("extraObjL1") or "0"
                        if route.get("districtObjLevel") == 2
                        else district_code
                    )
                    obj_l2_final = (
                        district_code
                        if route.get("districtObjLevel") == 2
                        else route.get("objL2")
                    )
                    try:
                        rows = await cache.get_statistics_data(
                            {
                                "orgId": route["orgId"],
                                "tableId": route["tblId"],
                                "objL1": obj_l1_final,
                                "objL2": obj_l2_final,
                                "itemId": route["itmId"],
                                "periodType": route.get("prdSe"),
                                "year": year,
                            },
                            lambda o1=obj_l1_final, o2=obj_l2_final: client.get_statistics_data(
                                {
                                    "orgId": route["orgId"],
                                    "tblId": route["tblId"],
                                    "objL1": o1,
                                    **({"objL2": o2} if o2 else {}),
                                    "itmId": route["itmId"],
                                    "prdSe": route.get("prdSe"),
                                    "newEstPrdCnt": None if start_prd else 1,
                                    "startPrdDe": start_prd,
                                    "endPrdDe": end_prd,
                                }
                            ),
                        )
                    except Exception:
                        continue
                    valid = [x for x in rows if parse_kosis_number(x.get("DT")) is not None]
                    if valid:
                        r = max(valid, key=lambda x: x.get("PRD_DE", ""))
                        period_label = format_period_with_type(
                            r["PRD_DE"], r.get("PRD_SE") or route.get("prdSe", "Y")
                        )
                        num_value = parse_kosis_number(r["DT"])
                        formatted = f"{num_value:,}" if num_value == int(num_value or 0) else f"{num_value:,}"
                        suffix = get_korean_particle(route.get("description", ""))
                        answer = (
                            f"{period_label} {district_name}의 {route.get('description')}{suffix} "
                            f"{formatted}{route.get('unit', '')}입니다.\n\n"
                            f"📊 출처: {route.get('description')} (KOSIS {route['tblId']})"
                        )
                        out: dict[str, Any] = {
                            "success": True,
                            "answer": answer,
                            "value": formatted,
                            "unit": route.get("unit"),
                            "period": period_label,
                            "source": {
                                "orgId": route["orgId"],
                                "tableId": route["tblId"],
                                "tableName": route.get("description"),
                            },
                        }
                        if route.get("isProjection"):
                            out["isProjection"] = True
                        return out
                if district_codes:
                    district_note = (
                        f"💡 {district_name} {route.get('description')}: "
                        "KOSIS 자치구 단위 데이터 미수록."
                    )
            except Exception:
                pass

        if district_name and keyword in DISTRICT_KEYWORD_TO_FILESN:
            try:
                excel_result = await fetch_kosis_excel(
                    districtName=district_name,
                    keyword=keyword,
                    year=year,
                    listOnly=False,
                )
                if excel_result.get("success") and excel_result.get("markdown"):
                    year_m = re.search(r"FILE(\d{4})", excel_result.get("tblId", ""))
                    year_label = year_m.group(1) if year_m else (str(year) if year else "")
                    source_name = f"{district_name} 통계연보"
                    hl = extract_district_highlight(excel_result["markdown"], keyword)
                    if hl.get("value"):
                        unit_label = (hl.get("unit") or param.get("unit") or "").strip()
                        formatted = _fmt_num(str(hl["value"]))
                        suffix = get_korean_particle(param.get("description", ""))
                        period_label = f"{year_label}년" if year_label else ""
                        subject = (
                            f"{period_label} {district_name}의"
                            if period_label
                            else f"{district_name}의"
                        )
                        return {
                            "success": True,
                            "answer": (
                                f"{subject} {param.get('description')}{suffix} "
                                f"{formatted}{unit_label}입니다.\n\n"
                                f"📊 출처: {source_name} (KOSIS {excel_result.get('tblId')})"
                            ),
                            "value": hl["value"],
                            "unit": unit_label,
                            "period": period_label or None,
                            "source": {
                                "orgId": excel_result.get("orgId"),
                                "tableId": excel_result.get("tblId"),
                                "tableName": source_name,
                            },
                        }
            except Exception as e:
                district_note = f'⚠️ "{district_name}" 엑셀 조회 예외: {str(e)[:150]}'

        if requested_region:
            if not param.get("regionCodes"):
                return {
                    "success": False,
                    "answer": f'"{keyword}" 통계는 지역별 조회를 지원하지 않습니다.',
                    "note": "전국 데이터만 제공됩니다.",
                }
            region_code = get_region_code(param, requested_region)
            if region_code is None:
                return {
                    "success": False,
                    "answer": f'"{requested_region}" 지역명을 인식하지 못해 조회를 중단했습니다.',
                    "note": "지원 지역: 17개 광역시도 약칭/풀네임. 전국은 region 생략.",
                }
            normalized = normalize_province_name(requested_region)
            if normalized != "전국":
                if param.get("regionObjLevel") == 2:
                    obj_l2 = region_code
                else:
                    obj_l1 = region_code
                region_name = normalized

        supported = param.get("supportedPeriods") or ["Y"]
        requested_period = period or supported[0]
        if requested_period not in supported:
            return {
                "success": False,
                "answer": f'"{query}"는 해당 주기 조회를 지원하지 않습니다.',
                "note": f"지원 주기: {', '.join(supported)}",
            }

        start_prd = end_prd = None
        if year:
            if requested_period == "Y":
                start_prd = end_prd = str(year)
            elif requested_period == "Q" and quarter:
                q = f"{year}{quarter:02d}"
                start_prd = end_prd = q
            elif requested_period == "M" and month:
                m = f"{year}{month:02d}"
                start_prd = end_prd = m
            elif requested_period == "Q":
                start_prd, end_prd = f"{year}01", f"{year}04"
            elif requested_period == "M":
                start_prd, end_prd = f"{year}01", f"{year}12"

        results = await cache.get_statistics_data(
            {
                "orgId": param["orgId"],
                "tableId": param["tableId"],
                "objL1": obj_l1,
                "objL2": obj_l2,
                "itemId": param["itemId"],
                "periodType": requested_period,
                "year": year,
            },
            lambda: client.get_statistics_data(
                {
                    "orgId": param["orgId"],
                    "tblId": param["tableId"],
                    "objL1": obj_l1,
                    "objL2": obj_l2,
                    "itmId": param["itemId"],
                    "prdSe": requested_period,
                    "newEstPrdCnt": None if start_prd else 1,
                    "startPrdDe": start_prd,
                    "endPrdDe": end_prd,
                }
            ),
        )
        valid = [r for r in results if parse_kosis_number(r.get("DT")) is not None]
        if not valid:
            return {
                "success": False,
                "answer": f'"{query}"에 대한 데이터를 찾을 수 없습니다.',
                "note": f"테이블: {param.get('tableName')} ({param.get('tableId')})",
            }
        latest = max(valid, key=lambda r: r.get("PRD_DE", ""))
        value = latest["DT"]
        period_fmt = format_period_with_type(latest["PRD_DE"], requested_period)
        if district_name:
            formatted = _fmt_num(value)
            suffix = get_korean_particle(param.get("description", ""))
            ref = (
                "참고로 전국"
                if region_name == "전국"
                else f"참고로 상위 지역 {region_name}의"
            )
            base = (
                f"{district_name} 단위 {param.get('description')} 데이터는 "
                f"KOSIS 자치구 통계에 수록돼 있지 않습니다. "
                f"{ref} {param.get('description')}{suffix} {period_fmt} 기준 {formatted}{param.get('unit', '')}입니다."
            )
        else:
            base = generate_natural_response(
                region_name=region_name,
                value=value,
                unit=param.get("unit", ""),
                period=period_fmt,
                description=param.get("description", ""),
            )
        projection_note = (
            "⚠️ 본 수치는 국가데이터처 장래추계 데이터입니다 (실측 아닌 미래 추계)."
            if param.get("isProjection")
            else None
        )
        provisional = (
            "⚠️ 인구동향조사 최근 시점 수치는 잠정치일 수 있습니다."
            if param["tableId"] in VITAL_STATS_TABLE_IDS
            and is_within_months(latest["PRD_DE"], 24)
            else None
        )
        notes = [n for n in (district_note, projection_note, provisional) if n]
        answer = (
            f"{base}\n\n📊 출처: {param.get('tableName')} (KOSIS {param['tableId']})"
            + (f"\n\n{chr(10).join(notes)}" if notes else "")
        )
        out = {
            "success": True,
            "answer": answer,
            "value": value,
            "unit": param.get("unit"),
            "period": period_fmt,
            "source": {
                "orgId": param["orgId"],
                "tableId": param["tableId"],
                "tableName": param.get("tableName"),
                "retrievedAt": datetime.now().date().isoformat(),
            },
        }
        if latest.get("LST_CHN_DE"):
            out["source"]["lastUpdated"] = latest["LST_CHN_DE"]
        if param.get("isProjection"):
            out["isProjection"] = True
        if notes:
            out["note"] = " / ".join(notes)
        return out
    except Exception as error:
        msg = str(error)
        if "데이터가 존재하지 않습니다" in msg:
            return {
                "success": False,
                "answer": f'"{query}" 데이터를 찾을 수 없습니다.',
                "note": f'search_statistics("{query}") 사용.',
            }
        return {
            "success": False,
            "answer": f"조회 중 오류가 발생했습니다: {msg}",
            "note": f'search_statistics("{query}")로 직접 검색해보세요.',
        }
