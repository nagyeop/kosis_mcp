"""Table meta lookup helpers."""

from __future__ import annotations

from typing import Any, TypedDict

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import get_kosis_client


class MetaItem(TypedDict, total=False):
    ITM_ID: str
    ITM_NM: str
    OBJ_NM: str
    OBJ_ID: str
    OBJ_ID_SN: str
    UP_ITM_ID: str


class MetaGroup(TypedDict):
    objNm: str
    objId: str
    objIdSn: str
    items: list[MetaItem]


async def fetch_table_meta(org_id: str, tbl_id: str) -> list[MetaItem]:
    cache = get_cache_manager()

    async def fetch() -> list[MetaItem]:
        client = get_kosis_client()
        rows = await client.get_table_meta(org_id, tbl_id, "ITM")
        return rows  # type: ignore[return-value]

    return await cache.get_table_meta({"orgId": org_id, "tblId": tbl_id, "type": "ITM"}, fetch)


def group_meta_by_obj(meta: list[MetaItem]) -> list[MetaGroup]:
    groups: dict[str, MetaGroup] = {}
    for r in meta:
        sn = r.get("OBJ_ID_SN") or "0"
        key = f"{sn}|{r.get('OBJ_ID')}"
        if key not in groups:
            groups[key] = {
                "objNm": r.get("OBJ_NM", ""),
                "objId": r.get("OBJ_ID", ""),
                "objIdSn": sn,
                "items": [],
            }
        groups[key]["items"].append(r)
    return sorted(groups.values(), key=lambda g: g["objIdSn"])


def find_itm_id_in_meta(
    meta: list[MetaItem], itm_name_query: str, obj_nm_hint: str | None = None
) -> dict[str, Any] | None:
    q = itm_name_query.strip()
    if not q:
        return None
    groups = group_meta_by_obj(meta)
    targets = (
        [g for g in groups if g["objNm"] == obj_nm_hint or obj_nm_hint in g["objNm"]]
        if obj_nm_hint
        else groups
    )
    tiers = [
        lambda it: it.get("ITM_NM") == q,
        lambda it: str(it.get("ITM_NM", "")).startswith(q),
        lambda it: q in str(it.get("ITM_NM", "")),
    ]
    for tier in tiers:
        for g in targets:
            hit = next((it for it in g["items"] if tier(it)), None)
            if hit:
                return {"match": hit, "group": g}
    return None


REGION_OBJ_HINTS = [
    "자치구별",
    "시군구별",
    "행정구역별",
    "지역별",
    "시도별",
    "구별",
    "시·군·구별",
]


async def resolve_dimensions(
    org_id: str,
    tbl_id: str,
    *,
    region_name: str | None = None,
    item_name: str | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    meta = await fetch_table_meta(org_id, tbl_id)
    groups = group_meta_by_obj(meta)
    resolved: list[dict[str, Any]] = []
    out: dict[str, Any] = {"resolved": resolved}

    item_matched = not item_name
    item_group = next(
        (g for g in groups if g["objId"] == "ITEM" or g["objNm"] == "항목"), None
    )
    if item_group:
        item = item_group["items"][0]
        if item_name:
            r = find_itm_id_in_meta(meta, item_name, item_group["objNm"])
            if r:
                item = r["match"]
                item_matched = True
        out["itmId"] = item["ITM_ID"]
        resolved.append(
            {
                "objNm": item_group["objNm"],
                "itmNm": item["ITM_NM"],
                "itmId": item["ITM_ID"],
                "reason": "region" if item_name and item_matched else "default",
            }
        )

    region_matched = not region_name
    dim_groups = [g for g in groups if g["objIdSn"] != "0" and g["objId"] != "ITEM"]
    candidates: dict[str, list[str]] = {}
    for g in dim_groups:
        picked: MetaItem | None = None
        reason = "default"
        override_name = (overrides or {}).get(g["objNm"])
        if override_name:
            r = find_itm_id_in_meta(meta, override_name, g["objNm"])
            if r:
                picked = r["match"]
                reason = "region"
        if not picked and region_name and any(
            h.replace("별", "") in g["objNm"] or g["objNm"] == h for h in REGION_OBJ_HINTS
        ):
            r = find_itm_id_in_meta(meta, region_name, g["objNm"])
            if r:
                picked = r["match"]
                reason = "region"
                region_matched = True
        if not picked and g["items"]:
            picked = g["items"][0]
        if picked:
            resolved.append(
                {
                    "objNm": g["objNm"],
                    "itmNm": picked["ITM_NM"],
                    "itmId": picked["ITM_ID"],
                    "reason": reason,
                }
            )
            sn = int(g["objIdSn"] or "0")
            if sn == 1:
                out["objL1"] = picked["ITM_ID"]
            elif sn == 2:
                out["objL2"] = picked["ITM_ID"]
            elif sn == 3:
                out["objL3"] = picked["ITM_ID"]
            elif sn == 4:
                out["objL4"] = picked["ITM_ID"]
        candidates[g["objNm"]] = [it["ITM_NM"] for it in g["items"][:10]]

    if not region_matched or not item_matched:
        out["unmatched"] = {}
        if not region_matched:
            out["unmatched"]["regionName"] = region_name
        if not item_matched:
            out["unmatched"]["itemName"] = item_name
    out["candidates"] = candidates
    return out


async def summarize_table_meta(
    org_id: str,
    tbl_id: str,
    *,
    sample_size: int = 10,
    filter: str | None = None,
) -> dict[str, Any]:
    meta = await fetch_table_meta(org_id, tbl_id)
    groups = group_meta_by_obj(meta)
    filt = (filter or "").strip()
    return {
        "orgId": org_id,
        "tblId": tbl_id,
        "groups": [
            {
                "objNm": g["objNm"],
                "objIdSn": g["objIdSn"],
                "totalItems": len(g["items"]),
                "sample": [
                    {"ITM_ID": it["ITM_ID"], "ITM_NM": it["ITM_NM"]}
                    for it in (
                        ([it for it in g["items"] if filt in it["ITM_NM"]] or g["items"])
                        if filt
                        else g["items"]
                    )[:sample_size]
                ],
            }
            for g in groups
        ],
    }
