"""keyword — 대표 지표 키워드(QuickStatsParam·자치구 route) → SeriesSpec."""

from __future__ import annotations

from typing import Any

from kosis_mcp.data.district_file_map import DISTRICT_OPENAPI_ROUTES
from kosis_mcp.data.quick_stats_params import QuickStatsParam, get_region_code
from kosis_mcp.series.resolve import RegionIndex, is_region_group
from kosis_mcp.series.spec import SeriesSpec
from kosis_mcp.utils.meta_lookup import fetch_table_meta, group_meta_by_obj
from kosis_mcp.utils.district_kosis_codes import get_district_kscd_candidates_for
from kosis_mcp.utils.regions import (
    AMBIGUOUS_DISTRICTS,
    PROVINCES,
    find_province_by_district,
    normalize_province_name,
)


async def _region_index(org_id: str, tbl_id: str, obj_l: int | None) -> RegionIndex | None:
    try:
        meta = await fetch_table_meta(org_id, tbl_id)
    except Exception:
        return None
    groups = [g for g in group_meta_by_obj(meta) if g["objId"] != "ITEM"]
    if obj_l is not None:
        group = next((g for g in groups if int(g["objIdSn"] or 0) == obj_l), None)
    else:
        group = next((g for g in groups if is_region_group(g["objNm"])), None)
    return RegionIndex(group["items"]) if group else None


async def resolve_region_codes(
    org_id: str, tbl_id: str, name: str, *, province: str | None = None, obj_l: int | None = None
) -> list[str]:
    """이름이 정확히 같은 지역 코드 전부(개편 전후 코드 공존). province를 주면 그 시도 안에서만."""
    idx = await _region_index(org_id, tbl_id, obj_l)
    if idx is None:
        return []
    short = normalize_province_name(province) if province else None
    return [
        c
        for c in idx.items
        if idx.name(c) == name.strip() and (short is None or idx.province(c) == short)
    ]


async def resolve_region_code(
    org_id: str, tbl_id: str, name: str, *, province: str | None = None, obj_l: int | None = None
) -> str | None:
    """정적 코드표가 실패했을 때 표의 live 메타로 지역 코드를 찾는다(행정구역 개편·신설 지역 대응).
    obj_l을 주면 그 objL 번호의 분류에서, 아니면 지역 분류에서 찾는다. 유일하게 맞을 때만 코드를 돌려준다."""
    idx = await _region_index(org_id, tbl_id, obj_l)
    if idx is None:
        return None
    query = f"{province} {name}" if province and province not in name else name
    codes, _ambiguous = idx.match(query)
    return codes[0] if len(codes) == 1 else None


def district_route(keyword: str) -> dict[str, Any] | None:
    return DISTRICT_OPENAPI_ROUTES.get(keyword)  # type: ignore[return-value]


def _route_codes(route: dict[str, Any], region_code: str) -> dict[str, str]:
    """districtObjLevel=2면 지역이 objL2, objL1은 extraObjL1(기본 '0')."""
    if route.get("districtObjLevel") == 2:
        codes = {"objL1": route.get("extraObjL1") or "0", "objL2": region_code}
    else:
        codes = {"objL1": region_code}
        if route.get("objL2"):
            codes["objL2"] = route["objL2"]
    return {**codes, "itmId": route["itmId"]}


def _param_codes(param: QuickStatsParam, region_code: str | None) -> dict[str, str]:
    """regionObjLevel=2면 지역이 objL2."""
    codes: dict[str, str] = {"itmId": param["itemId"]}
    obj_l1, obj_l2 = param.get("objL1"), param.get("objL2")
    if region_code is not None:
        if param.get("regionObjLevel") == 2:
            obj_l2 = region_code
        else:
            obj_l1 = region_code
    if obj_l1:
        codes["objL1"] = obj_l1
    if obj_l2:
        codes["objL2"] = obj_l2
    return codes


def province_hint(district: str, province: str | None):
    if province and district in AMBIGUOUS_DISTRICTS:
        short = normalize_province_name(province)
        if short in AMBIGUOUS_DISTRICTS[district]:
            return next((p for p in PROVINCES if p.shortName == short), None)
    return find_province_by_district(district)


def param_spec(
    param: QuickStatsParam,
    *,
    region: str | None = None,
    all_regions: bool = False,
    region_code: str | None = None,
) -> tuple[SeriesSpec | None, str]:
    """시도·전국 spec. → (spec | None(지역 인식 실패), 표시 지역명). region_code를 주면 그대로 쓴다."""
    region_name = "전국"
    if all_regions:
        region_code, region_name = "ALL", "ALL"
    elif region_code:
        region_name = normalize_province_name(region or region_code)
    elif region and normalize_province_name(region) != "전국":
        region_code = get_region_code(param, region)
        if region_code is None:
            return None, region
        region_name = normalize_province_name(region)
    spec: SeriesSpec = {
        "orgId": param["orgId"],
        "tableId": param["tableId"],
        "codes": _param_codes(param, region_code),
        "periodType": (param.get("supportedPeriods") or ["Y"])[0],  # type: ignore[typeddict-item]
    }
    return spec, region_name


async def district_spec(
    route: dict[str, Any], district: str, *, province: str | None = None, all_regions: bool = False
) -> SeriesSpec | None:
    """자치구 route spec. all_regions면 지역 차원을 ALL로."""
    if all_regions:
        code = "ALL"
    else:
        hint = province_hint(district, province)
        codes = await get_district_kscd_candidates_for(
            route["orgId"], route["tblId"], district, hint, route.get("objId") or "auto"
        )
        code = codes[0] if codes else await resolve_region_code(
            route["orgId"],
            route["tblId"],
            district,
            province=hint.shortName if hint else province,
            obj_l=2 if route.get("districtObjLevel") == 2 else None,
        )
        if not code:
            return None
    return {
        "orgId": route["orgId"],
        "tableId": route["tblId"],
        "codes": _route_codes(route, code),
        "periodType": route.get("prdSe", "Y"),
    }
