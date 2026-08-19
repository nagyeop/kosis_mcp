"""Province / district mapping."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import get_kosis_client

_DATA = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "_regions.json").read_text(
        encoding="utf-8"
    )
)


@dataclass(frozen=True)
class ProvinceInfo:
    orgId: str
    fullName: str
    shortName: str
    baseStatPrefix: str


PROVINCES: list[ProvinceInfo] = [ProvinceInfo(**p) for p in _DATA["PROVINCES"]]
AMBIGUOUS_DISTRICTS: dict[str, list[str]] = _DATA["AMBIGUOUS_DISTRICTS"]
PROVINCE_NAME_VARIANTS: list[dict[str, str]] = _DATA["PROVINCE_NAME_VARIANTS"]
DISTRICT_TO_PROVINCE: dict[str, str] = _DATA["DISTRICT_TO_PROVINCE"]
PROVINCE_NAME_TO_SHORT: dict[str, str] = _DATA["PROVINCE_NAME_TO_SHORT"]


def normalize_province_name(name: str) -> str:
    return PROVINCE_NAME_TO_SHORT.get(name.strip(), name.strip())


def find_province(name_or_short: str) -> ProvinceInfo | None:
    q = name_or_short.strip()
    for p in PROVINCES:
        if (
            p.fullName == q
            or p.shortName == q
            or p.fullName.startswith(q)
            or q.startswith(p.shortName)
        ):
            return p
    return None


def find_province_by_district(district_name: str) -> ProvinceInfo | None:
    org_id = DISTRICT_TO_PROVINCE.get(district_name.strip())
    if not org_id:
        return None
    return next((p for p in PROVINCES if p.orgId == org_id), None)


def parse_district_list_id(list_id: str) -> dict[str, str] | None:
    m = re.search(r"(\d{3})(\d{2})$", list_id)
    if not m:
        return None
    return {"orgId": m.group(1), "tblIdSeq": m.group(2)}


async def list_districts(org_id: str) -> list[dict[str, str]]:
    cache = get_cache_manager()

    async def fetch() -> list[dict[str, str]]:
        client = get_kosis_client()
        rows = await client.get_statistics_list("MT_OTITLE", org_id)
        return [
            {
                "LIST_NM": str(r.get("LIST_NM") or ""),
                "LIST_ID": str(r.get("LIST_ID") or ""),
            }
            for r in rows
        ]

    return await cache.get_statistics_list(
        {"kind": "province_districts", "orgId": org_id}, fetch
    )


async def resolve_district_file_table(
    district_name: str, year: int | None = None
) -> dict[str, Any] | None:
    prov = find_province_by_district(district_name)
    if not prov:
        return None
    districts = await list_districts(prov.orgId)
    cand = next((d for d in districts if d["LIST_NM"] == district_name), None)
    if not cand:
        return None
    sub_list = await list_districts(cand["LIST_ID"])
    if not sub_list:
        return None
    target = sub_list[0]
    parsed = parse_district_list_id(target["LIST_ID"])
    if not parsed:
        return None

    def build_tbl_id(y: int) -> str:
        seq = parsed["tblIdSeq"].zfill(3)[-3:]
        return f"DT_{parsed['orgId']}{seq}_FILE{y}"

    current_y = datetime.now().year
    years = [year] if year is not None else [current_y - 1, current_y - 2, current_y - 3]
    candidates = [build_tbl_id(y) for y in years]
    return {
        "orgId": parsed["orgId"],
        "tblId": candidates[0],
        "tblIdCandidates": candidates,
        "listNm": target["LIST_NM"],
    }


def is_province_base_stat(org_id: str, tbl_id: str) -> ProvinceInfo | None:
    p = next((x for x in PROVINCES if x.orgId == org_id), None)
    if not p:
        return None
    if tbl_id.startswith(p.baseStatPrefix):
        return p
    return None


def detect_region(query: str) -> dict[str, Any]:
    for name in DISTRICT_TO_PROVINCE:
        if name in query:
            return {
                "district": name,
                "province": next(
                    (p for p in PROVINCES if p.orgId == DISTRICT_TO_PROVINCE[name]),
                    None,
                ),
            }
    for p in PROVINCES:
        if p.fullName in query or p.shortName in query:
            return {"province": p}
    return {}
