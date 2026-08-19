"""Data formatting utilities."""

from __future__ import annotations

import math
from typing import Any


def simplify_statistics_data(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "period": format_period(item.get("PRD_DE", ""), item.get("PRD_SE", "")),
            "value": format_number(str(item.get("DT", ""))),
            "classification": _get_classification_name(item),
            "item": item.get("ITM_NM"),
            "unit": item.get("UNIT_NM"),
        }
        for item in items
    ]


def _get_classification_name(item: dict[str, Any]) -> str:
    names: list[str] = []
    for i in range(1, 9):
        name = item.get(f"C{i}_NM")
        if name:
            names.append(str(name))
    return " > ".join(names) if names else "-"


def format_period(period: str, period_type: str) -> str:
    if not period:
        return "-"
    if period_type == "Y":
        return f"{period}년"
    if period_type == "Q":
        return f"{period[:4]}년 {period[4:]}분기"
    if period_type == "M":
        return f"{period[:4]}년 {int(period[4:])}월"
    if period_type == "D":
        return f"{period[:4]}.{period[4:6]}.{period[6:]}"
    return period


def format_number(value: str) -> str:
    if not value or value in ("-", "..."):
        return value
    try:
        num = float(value.replace(",", ""))
    except ValueError:
        return value
    if math.isnan(num):
        return value
    if num == int(num) and abs(num) < 1e15:
        return f"{int(num):,}"
    return f"{num:,.2f}".rstrip("0").rstrip(".")


def parse_kosis_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    cleaned = str(raw).replace(",", "").strip()
    if cleaned == "":
        return None
    try:
        n = float(cleaned)
    except ValueError:
        return None
    return n if math.isfinite(n) else None


def calculate_change_rate(
    current: float, previous: float
) -> dict[str, Any]:
    if previous == 0:
        return {"rate": 0, "direction": "stable", "formatted": "-"}
    rate = ((current - previous) / abs(previous)) * 100
    direction = "up" if rate > 0.1 else "down" if rate < -0.1 else "stable"
    sign = "+" if rate > 0 else ""
    return {
        "rate": rate,
        "direction": direction,
        "formatted": f"{sign}{rate:.1f}%",
    }


def analyze_trend(values: list[float]) -> dict[str, Any]:
    if len(values) < 2:
        return {"trend": "stable", "avgGrowthRate": 0, "volatility": 0}
    changes: list[float] = []
    for i in range(1, len(values)):
        if values[i - 1] != 0:
            changes.append((values[i] - values[i - 1]) / abs(values[i - 1]) * 100)
    if not changes:
        return {"trend": "stable", "avgGrowthRate": 0, "volatility": 0}
    avg = sum(changes) / len(changes)
    variance = sum((v - avg) ** 2 for v in changes) / len(changes)
    volatility = math.sqrt(variance)
    if volatility > 20:
        trend = "fluctuating"
    elif avg > 2:
        trend = "increasing"
    elif avg < -2:
        trend = "decreasing"
    else:
        trend = "stable"
    return {"trend": trend, "avgGrowthRate": avg, "volatility": volatility}


def recommend_visualization(
    data_length: int, has_multiple_categories: bool, is_time_series: bool
) -> dict[str, str]:
    if is_time_series and data_length > 2:
        return {
            "type": "line",
            "reason": "시계열 데이터는 선 그래프로 추세를 파악하기 좋습니다.",
        }
    if has_multiple_categories and data_length <= 6:
        return {"type": "pie", "reason": "비율 비교는 파이 차트가 적합합니다."}
    if data_length <= 10:
        return {"type": "bar", "reason": "항목 비교는 막대 그래프가 효과적입니다."}
    return {"type": "table", "reason": "데이터가 많아 표 형식이 가장 적합합니다."}
