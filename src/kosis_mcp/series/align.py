"""align — 표·주기가 다른 계열을 한 시점으로 맞춘다."""

from __future__ import annotations

from typing import Any, Literal

from kosis_mcp.series.periods import PeriodError, normalize_period

AlignMode = Literal["common_latest", "latest_each"]

_YEAR_END = {"M": "12", "Q": "04", "H": "02"}  # 연말 시점 하위 코드


def valid_periods(series: list[dict[str, Any]]) -> set[str]:
    return {p["period"] for s in series for p in s["points"] if p["value"] is not None}


def pick_point(
    series: dict[str, Any], period_type: str, target: str | None
) -> tuple[dict[str, Any] | None, str | None]:
    """→ (point, note). target이 연도(4자리)이고 주기가 Y가 아니면 그 해 마지막 시점(연말값 우선)."""
    pts = [p for p in series["points"] if p["value"] is not None]
    if not pts:
        return None, None
    if target is None:
        return pts[-1], None
    exact = next((p for p in pts if p["period"] == target), None)
    if exact:
        return exact, None
    if len(target) == 4 and period_type != "Y":
        in_year = [p for p in pts if p["period"].startswith(target)]
        if not in_year:
            return None, None
        last = in_year[-1]
        end = _YEAR_END.get(period_type)
        is_year_end = bool(end) and last["period"].endswith(end)
        note = None if is_year_end else f"{target}년 연말값이 없어 {last['period']} 값을 사용"
        return last, note
    return None, None


def choose_targets(
    groups: list[dict[str, Any]],
    *,
    mode: AlignMode = "common_latest",
    period: str | None = None,
) -> tuple[list[str | None], list[str]]:
    """groups: [{periodType, series, label?}] (spec 단위). → (spec별 목표 시점, warnings).

    값이 없는 spec은 공통 시점 계산에서 뺀다(나머지 spec의 정렬을 깨지 않도록)."""
    warnings: list[str] = []
    targets: list[str | None] = [None] * len(groups)
    if period:
        for i, g in enumerate(groups):
            try:
                targets[i] = normalize_period(period, g["periodType"])
            except PeriodError:
                targets[i] = period
        if any(g["periodType"] == "Y" for g in groups) and len(period.strip()) > 4:
            warnings.append(f"연 주기 계열은 {period.strip()[:4]}년 값으로 맞췄습니다.")
        return targets, warnings
    if mode == "latest_each":
        return targets, warnings

    active = [i for i, g in enumerate(groups) if valid_periods(g["series"])]
    empty = [g.get("label") or f"s{i + 1}" for i, g in enumerate(groups) if i not in active]
    if empty:
        warnings.append(f"값이 없는 series {empty}는 공통 시점 계산에서 제외했습니다.")
    if not active:
        return targets, warnings
    if len(active) == 1:
        # 표 1개: 표의 최신 시점에 맞춘다(그 시점 값이 없는 계열은 비교에서 빠진다).
        i = active[0]
        targets[i] = max(valid_periods(groups[i]["series"]))
        return targets, warnings

    types = [groups[i]["periodType"] for i in active]
    if len(set(types)) == 1:
        common = set.intersection(*(valid_periods(groups[i]["series"]) for i in active))
        if common:
            for i in active:
                targets[i] = max(common)
            return targets, warnings
    else:
        years = [{p[:4] for p in valid_periods(groups[i]["series"])} for i in active]
        common_years = set.intersection(*years)
        if common_years:
            year = max(common_years)
            warnings.append(f"주기가 달라({'/'.join(dict.fromkeys(types))}) {year}년 기준으로 맞췄습니다(월·분기·반기는 연말값).")
            for i in active:
                targets[i] = year
            return targets, warnings
    warnings.append("공통 시점이 없어 계열마다 최신 시점을 사용했습니다.")
    return targets, warnings
