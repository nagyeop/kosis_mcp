"""resolve — SeriesSpec → KOSIS API 파라미터 (메타 기반 이름 매칭·기본값 보고)."""

from __future__ import annotations

from typing import Any, Literal

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import get_kosis_client
from kosis_mcp.series.spec import SeriesSpec
from kosis_mcp.utils.meta_lookup import MetaGroup, MetaItem, fetch_table_meta, group_meta_by_obj
from kosis_mcp.utils.regions import PROVINCES, normalize_province_name

TOTAL_NAMES = {"전국", "계", "합계", "총계", "전체", "소계"}
_REGION_GROUP_MARKS = ("행정구역", "시도", "시군구", "시·군·구", "자치구", "읍면동", "동읍면")
# '지역'은 '출생지역별'·'거주지역별' 같은 비지역 분류와 겹쳐 접두로만 인정한다.
_REGION_GROUP_PREFIXES = ("지역",)
_PROVINCE_SHORTS = {p.shortName for p in PROVINCES}
_PRD_SE_CODES = {"년": "Y", "반기": "H", "분기": "Q", "월": "M", "일": "D", "부정기": "IR"}
CANDIDATE_LIMIT = 15

RegionLevelName = Literal["total", "sido", "sigungu", "subdistrict", "other"]


def is_total_name(name: str | None) -> bool:
    return (name or "").strip() in TOTAL_NAMES


def is_province(name: str | None) -> bool:
    return normalize_province_name(name or "") in _PROVINCE_SHORTS


def is_region_group(obj_nm: str) -> bool:
    name = obj_nm.strip()
    return any(m in name for m in _REGION_GROUP_MARKS) or name.startswith(_REGION_GROUP_PREFIXES)


class RegionIndex:
    """지역 분류 항목의 트리 (code → name, parent). 수준·시도·조인 키를 계산한다."""

    def __init__(self, items: list[MetaItem]):
        self.items = {str(i["ITM_ID"]): i for i in items}
        self._parents = {str(i["UP_ITM_ID"]) for i in items if i.get("UP_ITM_ID")}
        self._level: dict[str, RegionLevelName] = {}

    def name(self, code: str) -> str:
        return str(self.items.get(code, {}).get("ITM_NM") or code)

    def parent(self, code: str) -> str | None:
        """논리적 부모. KOSIS 메타는 일반구(31011 장안구)의 상위를 시(31010)가 아닌 도(31)로 둔다 →
        끝자리가 0이 아닌 5자리 코드에 같은 앞 4자리+'0' 형제가 있으면 그 시를 부모로 본다."""
        item = self.items.get(code, {})
        up = item.get("UP_ITM_ID")
        up = str(up) if up and str(up) in self.items else None
        if len(code) == 5 and code.isdigit() and code[-1] != "0":
            si = code[:4] + "0"
            if si in self.items and str(self.items[si].get("UP_ITM_ID") or "") == (up or ""):
                # 형제 코드가 '시'일 때(일반구)·자신이 '출장소'일 때만. 남구(28170)→미추홀구(28177)처럼
                # 옛 이름 코드가 형제로 남은 경우는 별개 시군구다.
                if self.name(si).endswith("시") or self.name(code).endswith("출장소"):
                    return si
        return up

    def level(self, code: str) -> RegionLevelName:
        if code in self._level:
            return self._level[code]
        name = self.name(code)
        up = self.parent(code)
        if is_total_name(name):
            lv: RegionLevelName = "total"
        elif up is None:
            # 하위 지역을 가진 최상위 항목도 시도로 본다 (예: 2026-07 전남광주통합특별시).
            lv = "sido" if is_province(name) or code in self._parents else "other"
            if lv == "other" and len(code) == 5 and code.isdigit():
                lv = "sigungu"
        else:
            parent_lv = self.level(up)
            lv = {"sido": "sigungu", "sigungu": "subdistrict", "subdistrict": "subdistrict"}.get(
                parent_lv, "other"
            )
        self._level[code] = lv
        return lv

    def province(self, code: str) -> str | None:
        cur: str | None = code
        while cur is not None:
            if self.level(cur) == "sido":
                return normalize_province_name(self.name(cur))
            cur = self.parent(cur)
        return None

    def join_key(self, code: str) -> str:
        """표마다 코드 체계가 달라(부산 26 vs 21) 조인은 정규화한 이름으로 한다.
        하위 지역은 상위 경로를 포함한다(서울 강남구 신사동 vs 서울 관악구 신사동)."""
        lv = self.level(code)
        if lv == "total":
            return "전국"
        if lv == "sido":
            return normalize_province_name(self.name(code))
        parts: list[str] = []
        cur: str | None = code
        while cur is not None and self.level(cur) not in ("sido", "total"):
            parts.append(self.name(cur))
            cur = self.parent(cur)
        prov = self.province(code)
        return " ".join([*([prov] if prov else []), *reversed(parts)])

    def match(self, query: str) -> tuple[list[str], list[str]]:
        """→ (codes, ambiguous_labels). '부산 중구', '서울 강남구 신사동'처럼 상위 지역 접두를 받는다."""
        q = " ".join(query.split())
        if not q:
            return [], []
        if q in TOTAL_NAMES:
            return [c for c in self.items if self.level(c) == "total"][:1], []
        if is_province(q):
            short = normalize_province_name(q)
            hits = [c for c in self.items if self.level(c) == "sido" and self.join_key(c) == short]
            if hits:
                return hits[:1], []
        tokens = q.split()
        prov = normalize_province_name(tokens[0]) if len(tokens) > 1 and is_province(tokens[0]) else None
        rest = tokens[1:] if prov else tokens
        name = rest[-1]
        path = " ".join(rest)
        live = [c for c in self.items if self.level(c) != "total"]
        for tier in (
            lambda c: self.name(c) == name and self.join_key(c).endswith(path),
            lambda c: self.name(c) == q or self.join_key(c) == q,
            lambda c: self.name(c).startswith(name),
            lambda c: name in self.name(c),
        ):
            hits = [c for c in live if tier(c)]
            if prov:
                hits = [c for c in hits if self.province(c) == prov]
            if len(hits) == 1:
                return hits, []
            if len(hits) > 1:
                return [], list(dict.fromkeys(self.join_key(c) for c in hits))[:CANDIDATE_LIMIT]
        return [], []


def _match_items(group: MetaGroup, query: str) -> tuple[list[MetaItem], bool]:
    """→ (hits, ambiguous). 정확 일치(ID·이름)는 첫 항목, 부분 일치가 여러 개면 모호."""
    q = query.strip()
    if not q:
        return [], False
    for exact, tier in (
        (True, lambda it: str(it.get("ITM_ID")) == q),
        (True, lambda it: it.get("ITM_NM") == q),
        (False, lambda it: str(it.get("ITM_NM", "")).startswith(q)),
        (False, lambda it: q in str(it.get("ITM_NM", ""))),
    ):
        hits = [it for it in group["items"] if tier(it)]
        if hits:
            return hits, (not exact and len(hits) > 1)
    return [], False


def _default_item(group: MetaGroup) -> MetaItem:
    """기본값: 합계 이름 항목 → 첫 항목."""
    return next((it for it in group["items"] if is_total_name(it.get("ITM_NM"))), group["items"][0])


def _names(group: MetaGroup) -> list[str]:
    return [str(it.get("ITM_NM")) for it in group["items"][:CANDIDATE_LIMIT]]


def _period_code(prd_se: str) -> str:
    return _PRD_SE_CODES.get(prd_se.strip(), "F" if "년" in prd_se else prd_se)


async def table_period_types(org_id: str, tbl_id: str) -> list[dict[str, str]]:
    cache = get_cache_manager()

    async def fetch() -> list[dict[str, Any]]:
        return await get_kosis_client().get_table_meta(org_id, tbl_id, "PRD")

    try:
        rows = await cache.get_table_meta({"orgId": org_id, "tblId": tbl_id, "type": "PRD"}, fetch)
    except Exception:
        return []
    return [
        {
            "periodType": _period_code(str(r.get("PRD_SE") or "")),
            "start": str(r.get("STRT_PRD_DE") or ""),
            "end": str(r.get("END_PRD_DE") or ""),
        }
        for r in rows
        if r.get("PRD_SE")
    ]


def choose_period_type(
    available: list[dict[str, str]], prefer: Literal["Y", "finest"]
) -> str | None:
    codes = [a["periodType"] for a in available]
    if not codes:
        return None
    if prefer == "Y" and "Y" in codes:
        return "Y"
    order = ["M", "Q", "H", "Y", "D", "F", "IR"]
    return min(codes, key=lambda c: order.index(c) if c in order else len(order))


async def resolve_spec(
    spec: SeriesSpec, *, prefer_period: Literal["Y", "finest"] = "finest"
) -> dict[str, Any]:
    org_id, tbl_id = spec["orgId"], spec["tableId"]
    meta = await fetch_table_meta(org_id, tbl_id)
    groups = group_meta_by_obj(meta)
    item_group = next((g for g in groups if g["objId"] == "ITEM"), None)
    dim_groups = sorted(
        (g for g in groups if g["objId"] != "ITEM"), key=lambda g: int(g["objIdSn"] or 0)
    )
    codes = dict(spec.get("codes") or {})
    region_group = next((g for g in dim_groups if is_region_group(g["objNm"])), None) or next(
        (g for g in dim_groups if codes.get(f"objL{int(g['objIdSn'] or 0)}") == "ALL"), None
    )

    params: dict[str, str] = {}
    applied: list[dict[str, str]] = []
    unmatched: dict[str, Any] = {}
    candidates: dict[str, list[str]] = {}
    warnings: list[str] = []

    # 항목
    if spec.get("item") and not item_group and "itmId" not in codes:
        warnings.append("이 표에는 항목(ITEM) 분류가 없어 item을 적용하지 못했습니다.")
    if "itmId" in codes:
        params["itmId"] = codes["itmId"]
    elif item_group:
        item = spec.get("item")
        if item == "ALL":
            params["itmId"] = "ALL"
        elif item:
            ids: list[str] = []
            for q in [item] if isinstance(item, str) else item:
                hits, ambiguous = _match_items(item_group, str(q))
                if hits and not ambiguous:
                    ids.append(str(hits[0]["ITM_ID"]))
                else:
                    unmatched.setdefault("item", []).append(q)
                    candidates[item_group["objNm"]] = (
                        [str(h.get("ITM_NM")) for h in hits][:CANDIDATE_LIMIT] if ambiguous else _names(item_group)
                    )
            params["itmId"] = "+".join(ids)
        else:
            it = item_group["items"][0]
            params["itmId"] = str(it["ITM_ID"])
            applied.append({"objNm": item_group["objNm"], "itmNm": str(it["ITM_NM"]), "itmId": params["itmId"]})

    # 분류 차원 (objL 번호 = OBJ_ID_SN)
    filters = {str(k).strip(): v for k, v in (spec.get("filters") or {}).items()}
    if "" in filters:
        filters.pop("")
        warnings.append("빈 filters 키는 무시했습니다.")
    used_filters: set[str] = set()
    region_index = RegionIndex(region_group["items"]) if region_group else None
    region_key: str | None = None
    for g in dim_groups:
        key = f"objL{int(g['objIdSn'] or 0)}"
        if g is region_group:
            region_key = key
        if key in codes:
            params[key] = codes[key]
            continue
        if g is region_group and region_index and (spec.get("regions") or spec.get("level")):
            regions = spec.get("regions") or "ALL"
            if regions == "ALL":
                params[key] = "ALL"
            else:
                picked: list[str] = []
                for q in [regions] if isinstance(regions, str) else regions:
                    hits, ambiguous = region_index.match(q)
                    if hits:
                        picked.extend(hits)
                    else:
                        unmatched.setdefault("regions", []).append(q)
                        candidates[g["objNm"]] = ambiguous or [
                            region_index.join_key(c) for c in region_index.items
                            if region_index.level(c) in ("total", "sido")
                        ][:CANDIDATE_LIMIT]
                params[key] = "+".join(dict.fromkeys(picked))
            continue
        fkey = next((k for k in filters if k == g["objNm"]), None) or next(
            (k for k in filters if k not in used_filters and (k in g["objNm"] or g["objNm"] in k)), None
        )
        if fkey:
            used_filters.add(fkey)
            value = str(filters[fkey]).strip()
            if value == "ALL":
                params[key] = "ALL"
                continue
            hits, ambiguous = _match_items(g, value)
            if hits and not ambiguous:
                params[key] = str(hits[0]["ITM_ID"])
            else:
                unmatched.setdefault("filters", []).append({fkey: value})
                candidates[g["objNm"]] = (
                    [str(h.get("ITM_NM")) for h in hits][:CANDIDATE_LIMIT] if ambiguous else _names(g)
                )
            continue
        it = _default_item(g)
        params[key] = str(it["ITM_ID"])
        applied.append({"objNm": g["objNm"], "itmNm": str(it["ITM_NM"]), "itmId": params[key]})

    for k in set(filters) - used_filters:
        warnings.append(f"filters '{k}'에 해당하는 분류가 표에 없습니다. 분류: {[g['objNm'] for g in dim_groups]}")
    if spec.get("regions") and not region_group and "objL1" not in codes:
        warnings.append("이 표에는 지역 분류가 없어 regions를 적용하지 못했습니다.")

    available = await table_period_types(org_id, tbl_id)
    period_type = spec.get("periodType") or choose_period_type(available, prefer_period)
    if not period_type:
        unmatched["periodType"] = "표의 수록 주기를 확인하지 못했습니다. periodType을 지정하세요."
    elif not spec.get("periodType"):
        applied.append({"objNm": "주기", "itmNm": period_type, "itmId": period_type})
    elif available and period_type not in {a["periodType"] for a in available}:
        unmatched["periodType"] = f"{period_type} 주기가 없습니다. 가능: {[a['periodType'] for a in available]}"

    return {
        "params": params,
        "periodType": period_type,
        "periodTypes": available,
        "regionObjL": region_key,
        "regionIndex": region_index,
        "itemUnits": {
            str(it["ITM_ID"]): it.get("UNIT_NM") for it in (item_group["items"] if item_group else [])
        },
        "appliedDefaults": applied,
        "unmatched": unmatched,
        "candidates": candidates,
        "warnings": warnings,
    }
