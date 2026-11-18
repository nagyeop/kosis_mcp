"""analyze_trend / compare_values — 표 여러 개를 계열 단위로 분석·비교한다."""

from __future__ import annotations

import asyncio
import math
from typing import Any

from kosis_mcp.series.align import AlignMode, choose_targets, pick_point
from kosis_mcp.series.fetch import fetch_spec
from kosis_mcp.series.metrics import (
    DeriveError,
    cagr,
    evaluate,
    expr_names,
    growth,
    parse_expr,
    period_index,
    rank,
    share,
    trend_stats,
    versus,
)
from kosis_mcp.series.resolve import is_total_name
from kosis_mcp.series.spec import SeriesSpec, spec_label
from kosis_mcp.series.units import additive, comparable, normalize_value, parse_unit

MAX_TREND_SERIES = 20
_FETCH_CONCURRENCY = 4
# 이 오류는 해당 spec을 조회하지 못한 것 → 실패 응답. no_data는 경고로 두고 나머지로 진행한다.
_FAIL_KINDS = {"unmatched", "no_table", "too_large", "bad_period", "api"}
_FAIL_HINTS = {
    "unmatched": "candidates의 이름으로 item·regions·filters를 고치거나, get_table_info로 분류를 확인하세요.",
    "no_table": "find_tables 결과의 orgId·tableId를 그대로 넣으세요.",
    "too_large": "regions·level·item·filters를 좁히거나 period로 시점을 지정하세요.",
    "bad_period": "시점은 2025, 202509, 2025.09, 2025 3/4, 2025년 상반기 형식으로 지정하세요.",
    "api": "잠시 후 다시 시도하세요.",
}
_LEVEL_ORDER = {"sido": 0, "sigungu": 1, "subdistrict": 2, "other": 3, None: 4}


def _labels(specs: list[SeriesSpec]) -> list[str]:
    out: list[str] = []
    for i, s in enumerate(specs):
        label = spec_label(s, i)
        out.append(label if label not in out else f"{label}_{i + 1}")
    return out


def _check_specs(specs: list[SeriesSpec]) -> str | None:
    if not specs:
        return "series에 1개 이상의 {orgId, tableId}가 필요합니다. find_tables 결과의 tables[i]를 그대로 넣으세요."
    for i, s in enumerate(specs):
        if not isinstance(s, dict) or not s.get("orgId") or not s.get("tableId"):
            return f"series[{i}]에 orgId·tableId가 없습니다."
    return None


async def _fetch_all(specs: list[SeriesSpec], **kw: Any) -> list[dict[str, Any]]:
    """spec 조회를 동시 4개로 제한한다(spec당 KOSIS 호출 최대 3건: 메타·주기·데이터)."""
    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def one(spec: SeriesSpec) -> dict[str, Any]:
        async with sem:
            try:
                return await fetch_spec(spec, **kw)
            except Exception as e:  # 네트워크·timeout 등은 spec 단위 실패로
                return {"resolved": None, "series": [], "error": "api", "message": str(e)[:200]}

    return list(await asyncio.gather(*(one(s) for s in specs)))


def _failures(labels: list[str], specs: list[SeriesSpec], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for label, spec, res in zip(labels, specs, results):
        kind = res.get("error")
        if kind not in _FAIL_KINDS:
            continue
        item: dict[str, Any] = {"label": label, "orgId": spec["orgId"], "tableId": spec["tableId"], "error": kind}
        if kind == "unmatched" and res.get("resolved"):
            item["unmatched"] = res["resolved"]["unmatched"]
            item["candidates"] = res["resolved"]["candidates"]
        if res.get("message"):
            item["message"] = res["message"]
        item["hint"] = _FAIL_HINTS[kind]
        out.append(item)
    return out


def _failure_response(failures: list[dict[str, Any]]) -> dict[str, Any]:
    kinds = {f["error"] for f in failures}
    error = (
        "일부 series의 조건을 표에서 찾지 못했습니다."
        if kinds == {"unmatched"}
        else "일부 series를 조회하지 못했습니다: " + ", ".join(sorted(kinds))
    )
    return {"success": False, "error": error, "failures": failures}


def _no_data_response(labels: list[str], results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "success": False,
        "error": "조건에 해당하는 데이터가 없습니다.",
        "failures": [
            {"label": lb, "error": "no_data", "message": r.get("message")} for lb, r in zip(labels, results)
        ],
    }


def _series_meta(label: str, spec: SeriesSpec, res: dict[str, Any]) -> dict[str, Any]:
    resolved = res.get("resolved") or {}
    first = (res.get("series") or [{}])[0]
    meta: dict[str, Any] = {
        "label": label,
        "orgId": spec["orgId"],
        "tableId": spec["tableId"],
        "tableName": first.get("tableName"),
        "periodType": resolved.get("periodType"),
        "appliedDefaults": resolved.get("appliedDefaults") or [],
    }
    warnings = list(resolved.get("warnings") or [])
    if res.get("error") == "no_data":
        warnings.append(res.get("message") or "조건에 해당하는 데이터가 없습니다.")
    if warnings:
        meta["warnings"] = warnings
    return meta


def _series_name(label: str, s: dict[str, Any], sers: list[dict[str, Any]]) -> str:
    """spec 안에서 달라지는 부분(지역·facet)만 label 뒤에 붙인다."""
    parts = [label]
    if len({(x.get("region") or {}).get("key") for x in sers}) > 1 and s.get("region"):
        parts.append(s["region"]["key"])
    if len({x.get("facet") for x in sers}) > 1 and s.get("facet"):
        parts.append(s["facet"])
    return " · ".join(parts)


def _r(v: float | None, nd: int = 3) -> float | None:
    if v is None or not math.isfinite(v):
        return None
    return round(v, nd)


# ── analyze_trend ─────────────────────────────────────────────


async def analyze_trend(
    series: list[SeriesSpec],
    startPeriod: str | None = None,
    endPeriod: str | None = None,
    recentCount: int = 10,
) -> dict[str, Any]:
    specs = list(series or [])
    err = _check_specs(specs)
    if err:
        return {"success": False, "error": err}
    if recentCount < 2:
        return {"success": False, "error": "recentCount는 2 이상이어야 합니다."}
    labels = _labels(specs)
    results = await _fetch_all(specs, prefer_period="Y", start=startPeriod, end=endPeriod, recent=recentCount)
    failures = _failures(labels, specs, results)
    if failures:
        return _failure_response(failures)
    if not any(r["series"] for r in results):
        return _no_data_response(labels, results)

    warnings: list[str] = []
    out_series: list[dict[str, Any]] = []
    # 계열 상한은 spec마다 나눠 적용한다(앞 spec의 ALL이 뒤 spec을 밀어내지 않도록).
    per_spec = max(1, MAX_TREND_SERIES // len(specs))
    for label, spec, res in zip(labels, specs, results):
        ptype = (res.get("resolved") or {}).get("periodType") or spec.get("periodType") or "Y"
        sers = res["series"]
        if len(sers) > per_spec:
            dropped = [_series_name(label, s, sers) for s in sers[per_spec:]]
            warnings.append(
                f"{label}: 계열 {len(sers)}개 중 {per_spec}개만 분석했습니다. 제외: {dropped[:10]}"
                f"{' …' if len(dropped) > 10 else ''} (regions·item·filters로 좁히세요)"
            )
        for s in sers[:per_spec]:
            pts = [{"period": p["period"], "value": p["value"]} for p in s["points"]]
            out_series.append(
                {
                    "name": _series_name(label, s, sers),
                    "label": label,
                    "region": s.get("region"),
                    "facet": s.get("facet"),
                    "unit": s.get("unit"),
                    "periodType": ptype,
                    "analysis": trend_stats(pts, ptype),
                    "points": pts,
                }
            )

    out: dict[str, Any] = {
        "success": True,
        "series": out_series,
        "tables": [_series_meta(lb, sp, rs) for lb, sp, rs in zip(labels, specs, results)],
    }
    if len(out_series) > 1:
        comparison = _trend_comparison(out_series, warnings)
        if comparison:
            out["comparison"] = comparison
    if warnings:
        out["warnings"] = warnings
    return out


def _trend_comparison(series: list[dict[str, Any]], warnings: list[str]) -> dict[str, Any] | None:
    period_sets = [{p["period"] for p in s["points"] if p["value"] is not None} for s in series]
    types = {s["periodType"] for s in series}
    if len(types) > 1:
        # 주기가 다르면 연도 단위로 비교 (각 연도의 마지막 값).
        period_sets = [{p[:4] for p in ps} for ps in period_sets]
        warnings.append("주기가 다른 계열은 연도 단위(각 연도 마지막 값)로 비교했습니다.")
    common = set.intersection(*period_sets) if period_sets else set()
    if len(common) < 2:
        warnings.append("공통 구간이 2개 시점 미만이라 계열 간 증감률을 비교하지 못했습니다.")
        return None
    start, end = min(common), max(common)
    rows = []
    for s in series:
        ptype = s["periodType"] if len(types) == 1 else "Y"
        a, _ = pick_point(s, s["periodType"], start)
        b, _ = pick_point(s, s["periodType"], end)
        va, vb = (a or {}).get("value"), (b or {}).get("value")
        i0, i1 = period_index(start, ptype), period_index(end, ptype)
        years = (i1 - i0) if i0 is not None and i1 is not None else 0
        rows.append(
            {
                "name": s["name"],
                "start": va,
                "end": vb,
                "changeRate": _r(growth(va, vb)),
                "cagr": _r(cagr(va, vb, years)) if va is not None and vb is not None else None,
            }
        )
    # 한 지표로만 순위를 매긴다: 모든 계열에 CAGR이 있으면 CAGR, 아니면 기간 변화율.
    metric = "cagr" if all(r["cagr"] is not None for r in rows) else "changeRate"
    ranks = rank({r["name"]: r[metric] for r in rows})
    for r in rows:
        r["rank"] = ranks.get(r["name"])
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))
    return {"commonRange": {"start": start, "end": end}, "rankedBy": metric, "rows": rows}


# ── compare_values ────────────────────────────────────────────

_NO_REGION_KEY = "(전체)"


async def compare_values(
    series: list[SeriesSpec],
    period: str | None = None,
    align: AlignMode = "common_latest",
    derive: list[dict[str, str]] | None = None,
    top: int | None = None,
) -> dict[str, Any]:
    specs = list(series or [])
    err = _check_specs(specs)
    if err:
        return {"success": False, "error": err}
    if top is not None and top < 1:
        return {"success": False, "error": "top은 1 이상이어야 합니다."}
    labels = _labels(specs)
    derive = [dict(d) for d in (derive or [])]  # 호출자 dict를 바꾸지 않는다
    results = await _fetch_all(specs, prefer_period="finest", period=period)
    failures = _failures(labels, specs, results)
    if failures:
        return _failure_response(failures)
    if not any(r["series"] for r in results):
        return _no_data_response(labels, results)

    groups = [
        {
            "label": lb,
            "periodType": (r.get("resolved") or {}).get("periodType") or "Y",
            "series": r["series"],
        }
        for lb, r in zip(labels, results)
    ]
    targets, warnings = choose_targets(groups, mode=align, period=period)
    others_have_regions = [
        any(
            len({(s.get("region") or {}).get("key") for s in r["series"]}) > 1
            for j, r in enumerate(results)
            if j != i
        )
        for i in range(len(results))
    ]

    columns: dict[str, dict[str, Any]] = {}
    rows: dict[str, dict[str, Any]] = {}
    totals: dict[str, dict[str, Any]] = {}
    total_candidates: dict[str, int] = {}
    for idx, (label, spec, res, group, target) in enumerate(zip(labels, specs, results, groups, targets)):
        sers = res["series"]
        facets = _varying_facets(sers)
        multi_region = len({(s.get("region") or {}).get("key") for s in sers}) > 1
        multi_facet = any(f for f, _ in facets.values())
        has_region = any(s.get("region") for s in sers)
        missing: list[str] = []
        for s in sers:
            facet, facet_total = facets[id(s)]
            region = s.get("region")
            if multi_region:
                # 행 = 지역, 열 = series(·facet)
                col = f"{label}·{facet}" if facet else label
                row_key, level = region["key"], region["level"]
                is_total = bool(s.get("isTotal"))
            elif multi_facet:
                # 지역 1개(또는 없음): 행 = 항목·분류값
                col, row_key, level = label, facet, None
                is_total = facet_total
            elif not has_region and others_have_regions[idx]:
                # 지역 분류가 없는 표를 지역별 표와 섞음 → 전국(합계) 값으로만 비교된다.
                col, row_key, level, is_total = label, "전국", "total", True
                warnings.append(f"{label}: 지역 분류가 없는 표라 전국(합계) 값으로만 비교됩니다.")
            else:
                col = label
                row_key, level = (region["key"], region["level"]) if region else (_NO_REGION_KEY, None)
                is_total = False
            unit = parse_unit(s.get("unit"))
            column = columns.get(col)
            if column is not None and column["_unit"]["base"] != unit["base"]:
                # 한 열 안에서 단위가 다르면 단위별로 열을 나눈다.
                col = f"{col}[{unit['base'] or s.get('unit') or '-'}]"
                column = columns.get(col)
            if column is None:
                column = columns[col] = {
                    "label": col,
                    "series": label,
                    "orgId": spec["orgId"],
                    "tableId": spec["tableId"],
                    "tableName": s.get("tableName"),
                    "unit": unit["base"] or s.get("unit"),
                    "kind": unit["kind"],
                    "periodType": group["periodType"],
                    "periods": set(),
                    "_unit": unit,
                }
            if region and not multi_region and multi_facet:
                column["region"] = region["key"]
            point, note = pick_point(s, group["periodType"], target)
            if point is None:
                missing.append(row_key)
                continue
            cell: dict[str, Any] = {
                "value": normalize_value(point["value"], unit),
                "unit": unit["base"] or s.get("unit"),
                "period": point["period"],
            }
            if unit["scale"] != 1:
                cell["originalUnit"] = s.get("unit")
            if note:
                cell["note"] = note
            column["periods"].add(point["period"])
            if is_total:
                total_candidates[col] = total_candidates.get(col, 0) + 1
                if col not in totals:
                    totals[col] = {"key": row_key, **cell}
                continue
            row = rows.setdefault(row_key, {"key": row_key, "level": level, "values": {}})
            prev = row["values"].get(col)
            if prev is not None:
                if cell["period"] > prev["period"]:
                    # 같은 이름의 폐지 코드보다 최신 값을 쓴다.
                    row["values"][col] = cell
                    continue
                if cell["period"] < prev["period"]:
                    continue
                code = (region or {}).get("code") or s["key"]
                alt_key = f"{row_key} ({code})"
                warnings.append(f"'{row_key}' 이름이 중복되어 코드를 붙인 행 '{alt_key}'로 나눴습니다.")
                rows.setdefault(alt_key, {"key": alt_key, "level": level, "values": {}})["values"][col] = cell
                continue
            row["values"][col] = cell
        if missing:
            warnings.append(
                f"{label}: {target or '최신'} 시점 값이 없어 제외한 행 {len(missing)}개: {missing[:10]} "
                "(행정구역 개편·공표 지연 가능. align='latest_each'로 각자 최신값을 볼 수 있습니다)"
            )
    for col, n in total_candidates.items():
        if n > 1:
            warnings.append(f"{col}: 합계 후보가 {n}개라 첫 번째를 분모로 썼습니다. filters로 분류를 좁히세요.")

    col_list = list(columns.values())
    for c in col_list:
        periods = sorted(c.pop("periods"))
        c["period"] = periods[-1] if len(periods) == 1 else (periods or None)
        if len(periods) > 1:
            warnings.append(f"{c['label']}의 시점이 섞여 있습니다: {periods}")
        if c["label"] in totals:
            c["total"] = totals[c["label"]]
    _period_warnings(results, targets, warnings)

    levels = {r["level"] for r in rows.values() if r["level"]}
    if len(levels) > 1:
        warnings.append(f"행정 수준이 섞여 있어({', '.join(sorted(levels))}) 수준별로 순위를 매겼습니다.")

    for c in col_list:
        unit = c["_unit"]
        total = totals.get(c["label"])
        for r in rows.values():
            cell = r["values"].get(c["label"])
            if not cell or not total:
                continue
            if additive(unit):
                cell["share"] = _r(share(cell["value"], total["value"]))
            vs = versus(cell["value"], total["value"])
            if vs:
                cell["vsTotal"] = {k: _r(v) for k, v in vs.items()}

    _rank_into(rows, [c["label"] for c in col_list], lambda r, k: (r["values"].get(k) or {}).get("value"))
    notes = _cross_column(rows, col_list, [] if derive else warnings)

    derived_names: list[str] = []
    if derive:
        try:
            derived_names = _apply_derive(rows, col_list, derive)
        except DeriveError as e:
            return {"success": False, "error": str(e), "columns": [_public_col(c) for c in col_list]}
        _rank_into(rows, derived_names, lambda r, k: (r.get("derived") or {}).get(k))

    rank_keys = [*derived_names, *(c["label"] for c in col_list)]
    primary = next((k for k in rank_keys if any(k in (r.get("ranks") or {}) for r in rows.values())), None)

    def primary_rank(r: dict[str, Any]) -> int | None:
        return (r.get("ranks") or {}).get(primary) if primary else None

    ordered = sorted(
        rows.values(),
        key=lambda r: (
            _LEVEL_ORDER.get(r["level"], 3),
            primary_rank(r) is None,
            primary_rank(r) or 0,
        ),
    )
    if top and len(ordered) > top:
        warnings.append(f"{len(ordered)}행 중 {primary} 기준 수준별 상위 {top}행만 반환했습니다.")
        ordered = _top_per_level(ordered, top)

    out: dict[str, Any] = {
        "success": True,
        "rankedBy": primary,
        "columns": [_public_col(c) for c in col_list],
        "rows": ordered,
        "tables": [_series_meta(lb, sp, rs) for lb, sp, rs in zip(labels, specs, results)],
    }
    if derived_names:
        out["derived"] = [{"name": d["name"], "expr": d["expr"], "unit": d.get("unit")} for d in derive]
    if notes:
        out["notes"] = notes
    if warnings:
        out["warnings"] = list(dict.fromkeys(warnings))
    return out


def _varying_facets(sers: list[dict[str, Any]]) -> dict[int, tuple[str, bool]]:
    """spec 안에서 값이 달라지는 항목·분류(지역 제외)만 facet으로.
    → id(series) → (facet, 합계 여부). 달라지는 분류값이 모두 합계 이름일 때만 합계로 본다."""
    vary_item = len({s["item"]["id"] for s in sers}) > 1
    dim_values: dict[str, set[str]] = {}
    for s in sers:
        for d in s["dims"]:
            if not s.get("region") or d["code"] != s["region"]["code"]:
                dim_values.setdefault(str(d.get("objNm")), set()).add(d["code"])
    vary_dims = {k for k, v in dim_values.items() if len(v) > 1}
    out: dict[int, tuple[str, bool]] = {}
    for s in sers:
        item_name = str(s["item"]["name"])
        dim_names = [
            str(d["name"])
            for d in s["dims"]
            if str(d.get("objNm")) in vary_dims and (not s.get("region") or d["code"] != s["region"]["code"])
        ]
        parts = [item_name] if vary_item else []
        names_for_total = [*parts, *dim_names]
        out[id(s)] = (
            " · ".join([*parts, *dim_names]),
            bool(names_for_total) and all(is_total_name(n) for n in names_for_total),
        )
    return out


def _public_col(c: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in c.items() if not k.startswith("_")}


def _period_warnings(results: list[dict[str, Any]], targets: list[str | None], warnings: list[str]) -> None:
    for res, target in zip(results, targets):
        if not target:
            continue
        latest = max((p["period"] for s in res["series"] for p in s["points"] if p["value"] is not None), default=None)
        if latest and latest[: len(target)] > target:
            warnings.append(f"공통 시점 {target}에 맞추느라 더 최신 값({latest})이 있는 계열도 {target} 값을 사용했습니다.")


def _rank_into(rows: dict[str, dict[str, Any]], keys: list[str], getter: Any) -> None:
    by_level: dict[Any, list[dict[str, Any]]] = {}
    for r in rows.values():
        by_level.setdefault(r["level"], []).append(r)
    for key in keys:
        for level_rows in by_level.values():
            ranks = rank({id(r): getter(r, key) for r in level_rows})
            for r in level_rows:
                if id(r) in ranks:
                    r.setdefault("ranks", {})[key] = ranks[id(r)]


def _cross_column(
    rows: dict[str, dict[str, Any]], cols: list[dict[str, Any]], warnings: list[str]
) -> list[dict[str, Any]]:
    """같은 단위·성격의 열이 다른 표(series)에 있으면 첫 열 대비 차이를 계산한다(같은 개념·다른 표/조사)."""
    if len(cols) < 2:
        return []
    base = cols[0]

    def overlaps(c: dict[str, Any]) -> bool:
        return any(base["label"] in r["values"] and c["label"] in r["values"] for r in rows.values())

    # 같은 spec의 facet 열끼리(s1·남자 vs s1·여자)는 차이를 내지 않는다.
    candidates = [c for c in cols[1:] if c["series"] != base["series"]]
    others = [c for c in candidates if comparable(base["_unit"], c["_unit"]) and overlaps(c)]
    skipped = [c["label"] for c in candidates if c not in others and overlaps(c)]
    if skipped:
        warnings.append(
            f"{base['label']}와 단위·성격이 달라 차이를 계산하지 않은 열: {skipped}. 비율이 필요하면 derive를 쓰세요."
        )
    if not others:
        return []
    for r in rows.values():
        a = (r["values"].get(base["label"]) or {}).get("value")
        diffs = {}
        for c in others:
            b = (r["values"].get(c["label"]) or {}).get("value")
            if a is not None and b is not None:
                diffs[c["label"]] = {"diff": _r(b - a), "rate": _r(growth(a, b))}
        if diffs:
            r["diffFrom"] = {"base": base["label"], **diffs}
    tables = {(c["orgId"], c["tableId"]) for c in [base, *others]}
    if len(tables) < 2:
        return []
    return [
        {
            "type": "definition",
            "message": "서로 다른 통계표의 값입니다. 조사 방식·기준 시점·집계 범위가 다를 수 있으니 explain_statistic으로 정의를 확인하세요.",
            "tables": [
                {"label": c["label"], "tableName": c["tableName"], "orgId": c["orgId"], "tableId": c["tableId"], "period": c["period"]}
                for c in [base, *others]
            ],
        }
    ]


def _apply_derive(
    rows: dict[str, dict[str, Any]], cols: list[dict[str, Any]], derive: list[dict[str, str]]
) -> list[str]:
    alias = {f"c{i + 1}": c["label"] for i, c in enumerate(cols)}
    alias.update({c["label"]: c["label"] for c in cols if c["label"].isidentifier()})
    names: list[str] = []
    for d in derive:
        name, expr = d.get("name"), d.get("expr")
        if not name or not expr:
            raise DeriveError("derive 항목에는 name과 expr이 필요합니다.")
        tree = parse_expr(expr)
        unknown = expr_names(expr) - set(alias)
        if unknown:
            raise DeriveError(f"derive '{name}'의 알 수 없는 이름 {sorted(unknown)}. 사용 가능: {sorted(alias)}")
        d.setdefault("unit", _derived_unit(expr, alias, cols))
        for r in rows.values():
            env = {k: (r["values"].get(v) or {}).get("value") for k, v in alias.items()}
            r.setdefault("derived", {})[name] = _r(evaluate(tree, env), 6)
        names.append(name)
    return names


def _derived_unit(expr: str, alias: dict[str, str], cols: list[dict[str, Any]]) -> str | None:
    parts = [p.strip() for p in expr.split("/")]
    if len(parts) != 2 or not all(p in alias for p in parts):
        return None
    unit = {c["label"]: c["unit"] for c in cols}
    a, b = unit.get(alias[parts[0]]), unit.get(alias[parts[1]])
    if not a or not b:
        return None
    return "비율" if a == b else f"{a}/{b}"


def _top_per_level(rows: list[dict[str, Any]], top: int) -> list[dict[str, Any]]:
    out, count = [], {}
    for r in rows:
        n = count.get(r["level"], 0)
        if n < top:
            out.append(r)
            count[r["level"]] = n + 1
    return out
