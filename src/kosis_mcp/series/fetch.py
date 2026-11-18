"""fetch — 데이터 조회 후 원시 행을 계열 키 (ITM_ID, C1..C8)로 묶는다."""

from __future__ import annotations

from typing import Any

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import KosisApiError, get_kosis_client
from kosis_mcp.series.periods import PeriodError, far_end, normalize_period, shift_back, year_bounds
from kosis_mcp.series.resolve import RegionIndex, is_total_name, resolve_spec
from kosis_mcp.series.spec import SeriesSpec
from kosis_mcp.utils.data_formatter import parse_kosis_number

_DIMS = range(1, 9)


async def fetch_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    """캐시 키 = API 파라미터 전체 (키 충돌 방지)."""
    cache = get_cache_manager()
    clean = {k: v for k, v in params.items() if v is not None}

    async def fetch() -> list[dict[str, Any]]:
        return await get_kosis_client().get_statistics_data(clean)

    return await cache.get_statistics_data(clean, fetch)


def group_rows(
    rows: list[dict[str, Any]],
    *,
    region_objl: str | None = None,
    region_index: RegionIndex | None = None,
    item_units: dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """원시 행 → Series 리스트 (등장 순서 유지, points는 시점 오름차순)."""
    region_dim = int(region_objl[4:]) if region_objl else None
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for r in rows:
        key = (str(r.get("ITM_ID") or ""), *(str(r.get(f"C{i}") or "") for i in _DIMS))
        s = by_key.get(key)
        if s is None:
            dims = []
            region: dict[str, Any] | None = None
            for i in _DIMS:
                code = r.get(f"C{i}")
                if code is None:
                    continue
                dim = {
                    "objNm": r.get(f"C{i}_OBJ_NM"),
                    "code": str(code),
                    "name": r.get(f"C{i}_NM"),
                }
                dims.append(dim)
                if i == region_dim:
                    code_s = str(code)
                    if region_index and code_s in region_index.items:
                        region = {
                            "code": code_s,
                            "name": dim["name"],
                            "level": region_index.level(code_s),
                            "key": region_index.join_key(code_s),
                        }
                    else:
                        region = {
                            "code": code_s,
                            "name": dim["name"],
                            "level": "total" if is_total_name(dim["name"]) else "other",
                            "key": dim["name"],
                        }
            item_id = str(r.get("ITM_ID") or "")
            s = {
                "key": "|".join(key),
                "item": {"id": item_id, "name": r.get("ITM_NM")},
                "dims": dims,
                "region": region,
                "unit": r.get("UNIT_NM") or (item_units or {}).get(item_id),
                "tableName": r.get("TBL_NM"),
                "points": [],
            }
            by_key[key] = s
        s["points"].append(
            {"period": str(r.get("PRD_DE")), "value": parse_kosis_number(r.get("DT")), "raw": r.get("DT")}
        )
    out = list(by_key.values())
    for s in out:
        s["points"].sort(key=lambda p: p["period"])
        non_region = [d for d in s["dims"] if not s["region"] or d["code"] != s["region"]["code"]]
        s["facet"] = " · ".join(
            str(x) for x in [s["item"]["name"], *(d["name"] for d in non_region)] if x
        )
        s["isTotal"] = bool(s["region"] and s["region"]["level"] == "total")
    return out


# 기본 조회 구간: 표 간 공표 시차(연 1~2년)를 덮을 만큼.
DEFAULT_RECENT = {"Y": 5, "H": 6, "Q": 12, "M": 36}

_ERROR_KINDS = (
    ("40,000셀", "too_large", "조회 셀이 KOSIS 한도(40,000)를 넘습니다. regions·level·item·filters·기간을 좁히세요."),
    ("수록 시점", "bad_period", "시점 형식이 표 주기와 맞지 않습니다."),
    ("데이터가 존재하지", "no_data", "조건에 해당하는 데이터가 없습니다(수록 범위·조건 확인)."),
)


def classify_error(message: str) -> tuple[str, str]:
    for mark, kind, hint in _ERROR_KINDS:
        if mark in message:
            return kind, hint
    return "api", message


def period_params(
    period_type: str,
    *,
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    recent: int | None = None,
) -> dict[str, Any]:
    """period(시점 1개, 연도면 그 해 전체) > start/end > recent. 입력은 표 주기 형식으로 정규화한다."""
    if period:
        p = normalize_period(period, period_type)
        if len(p) == 4 and period_type not in ("Y", "F", "IR"):
            lo, hi = year_bounds(p, period_type)
            return {"startPrdDe": lo, "endPrdDe": hi}
        return {"startPrdDe": p, "endPrdDe": p}
    n = recent or DEFAULT_RECENT.get(period_type, 5)
    if start or end:
        lo = hi = None
        if start:
            lo = normalize_period(start, period_type)
            if len(lo) == 4 and period_type not in ("Y", "F", "IR"):
                lo = year_bounds(lo, period_type)[0]
        if end:
            hi = normalize_period(end, period_type)
            if len(hi) == 4 and period_type not in ("Y", "F", "IR"):
                hi = year_bounds(hi, period_type)[1]
        if lo and not hi:
            # KOSIS는 startPrdDe만 주면 그 한 시점만 돌려준다 → 끝을 먼 미래로.
            hi = far_end(period_type)
        if hi and not lo:
            lo = shift_back(hi, period_type, n - 1)
            if lo is None:
                return {"endPrdDe": hi, "newEstPrdCnt": n}
        return {"startPrdDe": lo, "endPrdDe": hi}
    return {"newEstPrdCnt": n}


async def fetch_spec(
    spec: SeriesSpec,
    *,
    prefer_period: str = "finest",
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
    recent: int | None = None,
) -> dict[str, Any]:
    """spec → {resolved, series, params} 또는 {error, message, resolved?, series: []}.

    error: unmatched | no_table | no_data | too_large | bad_period | api
    """
    try:
        resolved = await resolve_spec(spec, prefer_period=prefer_period)  # type: ignore[arg-type]
    except KosisApiError as e:
        kind, hint = classify_error(str(e))
        if kind == "no_data":
            return {"resolved": None, "series": [], "error": "no_table", "message": "표를 찾을 수 없습니다(orgId·tableId 확인)."}
        return {"resolved": None, "series": [], "error": kind, "message": hint}
    if resolved["unmatched"]:
        return {"resolved": resolved, "series": [], "error": "unmatched"}
    period_type = resolved["periodType"]
    try:
        window = period_params(period_type, period=period, start=start, end=end, recent=recent)
    except PeriodError as e:
        return {"resolved": resolved, "series": [], "error": "bad_period", "message": str(e)}
    params = {
        "orgId": spec["orgId"],
        "tblId": spec["tableId"],
        **resolved["params"],
        "prdSe": period_type,
        **window,
    }
    try:
        rows = await fetch_rows(params)
    except KosisApiError as e:
        kind, hint = classify_error(str(e))
        if kind == "no_data":
            ranges = [f"{a['periodType']} {a['start']}~{a['end']}" for a in resolved["periodTypes"]]
            hint = f"{hint} 수록 범위: {ranges}" if ranges else hint
        return {"resolved": resolved, "series": [], "error": kind, "message": hint, "params": params}
    series = group_rows(
        rows,
        region_objl=resolved["regionObjL"],
        region_index=resolved["regionIndex"],
        item_units=resolved["itemUnits"],
    )
    if not any(p["value"] is not None for s in series for p in s["points"]):
        return {"resolved": resolved, "series": [], "error": "no_data", "message": "조건에 해당하는 값이 없습니다.", "params": params}
    level = spec.get("level")
    if level:
        kept = [s for s in series if not s["region"] or s["region"]["level"] in (level, "total")]
        if any(not s["isTotal"] for s in kept) or not any(not s["isTotal"] for s in series):
            series = kept
        else:
            # 메타에 상위 지역 정보가 없는 표: 수준을 판정할 수 없어 거르지 않는다.
            resolved["warnings"].append(f"지역 수준({level})을 판정할 수 없어 전체 지역을 반환했습니다.")
    return {"resolved": resolved, "series": series, "params": params}
