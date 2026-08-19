"""Dynamic KOSIS district administrative code lookup."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from kosis_mcp.client import get_kosis_client
from kosis_mcp.utils.regions import (
    ProvinceInfo,
    find_province_by_district,
    normalize_province_name,
)

PROVINCE_ORGID_TO_KSCD: dict[str, str] = {
    "201": "11",
    "202": "26",
    "203": "27",
    "204": "28",
    "205": "29",
    "206": "30",
    "207": "31",
    "208": "36",
    "210": "41",
    "211": "51",
    "212": "43",
    "213": "44",
    "214": "52",
    "215": "46",
    "216": "47",
    "217": "48",
    "218": "50",
}

OBJ_ID_CANDIDATES = ("A", "B", "SGG", "region", "C1", "C2")

KOSIS_DIST_CODE_PROVINCE: dict[str, str] = {
    "1": "경기",
    "2": "강원",
    "3": "충북",
    "4": "충남",
    "5": "전북",
    "6": "전남",
    "7": "경북",
    "8": "경남",
    "9": "제주",
}


def get_province_kscd(org_id: str) -> str | None:
    return PROVINCE_ORGID_TO_KSCD.get(org_id)


class TableCodeIndex:
    def __init__(self) -> None:
        self.by_province_name: dict[str, list[str]] = {}
        self.province_itm_id_by_name: dict[str, str] = {}
        self.by_itm_name: dict[str, str] = {}
        self.ambiguous_itm_names: set[str] = set()


_cached: dict[str, TableCodeIndex] = {}
_loading: dict[str, asyncio.Future[TableCodeIndex]] = {}


def _has_district_entries(idx: TableCodeIndex) -> bool:
    if idx.by_province_name:
        return True
    count = 0
    for name in idx.by_itm_name:
        last = name.split()[-1] if name.split() else name
        if not re.match(r"^[가-힣]{1,4}(구|군|시)$", last):
            continue
        if normalize_province_name(name) != name or normalize_province_name(last) != last:
            continue
        count += 1
        if count >= 10:
            return True
    return False


async def _load_district_codes_for(
    org_id: str, tbl_id: str, obj_id_hint: str = "auto"
) -> TableCodeIndex:
    cache_key = f"{org_id}:{tbl_id}:{obj_id_hint}"
    if cache_key in _cached:
        return _cached[cache_key]
    if cache_key in _loading:
        return await _loading[cache_key]

    loop = asyncio.get_running_loop()
    fut: asyncio.Future[TableCodeIndex] = loop.create_future()
    _loading[cache_key] = fut

    try:
        client = get_kosis_client()
        meta = await client.get_table_meta(org_id, tbl_id, "ITM")

        def build_index(obj_id: str) -> TableCodeIndex | None:
            province_itm_id_by_name: dict[str, str] = {}
            for r in meta:
                if r.get("OBJ_ID") != obj_id:
                    continue
                parent = (r.get("UP_ITM_ID") or "").strip()
                if parent:
                    continue
                if not r.get("ITM_NM") or not r.get("ITM_ID"):
                    continue
                if r["ITM_NM"] not in province_itm_id_by_name:
                    province_itm_id_by_name[r["ITM_NM"]] = r["ITM_ID"]

            province_name_by_itm_id = {
                id_: normalize_province_name(name)
                for name, id_ in province_itm_id_by_name.items()
            }

            idx = TableCodeIndex()
            idx.province_itm_id_by_name = province_itm_id_by_name
            for r in meta:
                if r.get("OBJ_ID") != obj_id:
                    continue
                if not r.get("ITM_NM") or not r.get("ITM_ID"):
                    continue
                parent_id = r.get("UP_ITM_ID")
                if parent_id and str(parent_id).strip():
                    province_name = province_name_by_itm_id.get(str(parent_id))
                    if province_name:
                        key = f"{province_name}:{r['ITM_NM']}"
                        arr = idx.by_province_name.setdefault(key, [])
                        if r["ITM_ID"] not in arr:
                            arr.append(r["ITM_ID"])
                else:
                    if r["ITM_NM"] in idx.by_itm_name:
                        idx.ambiguous_itm_names.add(r["ITM_NM"])
                    else:
                        idx.by_itm_name[r["ITM_NM"]] = r["ITM_ID"]
                    m = re.match(r"^3(\d)\d\d$", r["ITM_ID"])
                    if m:
                        prov_short = KOSIS_DIST_CODE_PROVINCE.get(m.group(1))
                        if prov_short:
                            idx.by_itm_name[f"{prov_short} {r['ITM_NM']}"] = r["ITM_ID"]

            if not idx.by_province_name and not idx.by_itm_name:
                return None
            return idx

        try_order = OBJ_ID_CANDIDATES if obj_id_hint == "auto" else (obj_id_hint,)
        result: TableCodeIndex | None = None
        for oid in try_order:
            idx = build_index(oid)
            if not idx:
                continue
            if obj_id_hint == "auto" and not _has_district_entries(idx):
                continue
            result = idx
            break
        final = result or TableCodeIndex()
        _cached[cache_key] = final
        fut.set_result(final)
        return final
    except Exception as e:
        fut.set_exception(e)
        raise
    finally:
        _loading.pop(cache_key, None)


async def get_district_kscd_candidates_for(
    org_id: str,
    tbl_id: str,
    district_name: str,
    province_hint: ProvinceInfo | None = None,
    obj_id_hint: str = "auto",
) -> list[str]:
    prov = province_hint or find_province_by_district(district_name)
    idx = await _load_district_codes_for(org_id, tbl_id, obj_id_hint)
    if prov:
        codes = idx.by_province_name.get(f"{prov.shortName}:{district_name}")
        if codes:
            return codes
    if idx.by_itm_name:
        if district_name not in idx.ambiguous_itm_names:
            single = idx.by_itm_name.get(district_name)
            if single:
                return [single]
        if prov:
            combined_short = idx.by_itm_name.get(f"{prov.shortName} {district_name}")
            if combined_short:
                return [combined_short]
            combined_full = idx.by_itm_name.get(f"{prov.fullName} {district_name}")
            if combined_full:
                return [combined_full]
    return []


async def get_district_kscd_code_for(
    org_id: str,
    tbl_id: str,
    district_name: str,
    province_hint: ProvinceInfo | None = None,
    obj_id_hint: str = "auto",
) -> str | None:
    codes = await get_district_kscd_candidates_for(
        org_id, tbl_id, district_name, province_hint, obj_id_hint
    )
    return codes[0] if codes else None


async def get_district_kscd_code(
    district_name: str, province_hint: ProvinceInfo | None = None
) -> str | None:
    return await get_district_kscd_code_for(
        "101", "DT_1B040A3", district_name, province_hint
    )


def invalidate_district_kscd_cache() -> None:
    _cached.clear()
