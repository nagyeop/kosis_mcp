"""metrics — 시계열·횡단 비교 지표 (순수 함수)."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Hashable, Mapping
from typing import Any

from kosis_mcp.utils.data_formatter import analyze_trend, calculate_change_rate

_PERIODS_PER_YEAR = {"Y": 1, "H": 2, "Q": 4, "M": 12}


def period_index(period: str, period_type: str) -> float | None:
    """PRD_DE → 연 단위 위치 (2024 → 2024.0, 202403(M) → 2024.1667)."""
    try:
        year = int(period[:4])
    except (TypeError, ValueError):
        return None
    per = _PERIODS_PER_YEAR.get(period_type)
    if per is None:
        return float(year)
    if per == 1:
        return float(year)
    try:
        sub = int(period[4:]) if len(period) > 4 else per
    except ValueError:
        return None
    return year + (sub - 1) / per


def same_period_last_year(period: str) -> str | None:
    if len(period) < 4 or not period[:4].isdigit():
        return None
    return f"{int(period[:4]) - 1}{period[4:]}"


def cagr(first: float, last: float, years: float) -> float | None:
    if years <= 0 or first <= 0 or last <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def growth(first: float | None, last: float | None) -> float | None:
    if first is None or last is None or first == 0:
        return None
    return (last - first) / abs(first) * 100


def rank(values: Mapping[Hashable, float | None], descending: bool = True) -> dict[Hashable, int]:
    """동순위 처리(1,2,2,4). None 값은 순위에서 뺀다."""
    valid = [(k, v) for k, v in values.items() if v is not None]
    valid.sort(key=lambda kv: kv[1], reverse=descending)
    out: dict[Hashable, int] = {}
    prev: float | None = None
    current = 0
    for i, (k, v) in enumerate(valid, start=1):
        if v != prev:
            current = i
            prev = v
        out[k] = current
    return out


def share(value: float | None, total: float | None) -> float | None:
    if value is None or not total:
        return None
    return value / total * 100


def versus(value: float | None, ref: float | None) -> dict[str, float | None] | None:
    if value is None or ref is None:
        return None
    return {"diff": value - ref, "ratio": (value / ref * 100) if ref else None}


def trend_stats(points: list[dict[str, Any]], period_type: str) -> dict[str, Any]:
    """points: [{period, value}] (시점 오름차순, value None 제외 전제)."""
    pts = [p for p in points if p.get("value") is not None]
    if not pts:
        return {"trend": "unknown", "points": 0}
    values = [p["value"] for p in pts]
    base = analyze_trend(values)
    first, last = pts[0], pts[-1]
    out: dict[str, Any] = {
        "trend": base["trend"],
        "avgGrowthRate": round(base["avgGrowthRate"], 3),
        "volatility": round(base["volatility"], 3),
        "start": {"period": first["period"], "value": first["value"]},
        "end": {"period": last["period"], "value": last["value"]},
        "totalChangeRate": _round(growth(first["value"], last["value"])),
        "max": _pv(max(pts, key=lambda p: p["value"])),
        "min": _pv(min(pts, key=lambda p: p["value"])),
        "points": len(pts),
    }
    i0, i1 = period_index(first["period"], period_type), period_index(last["period"], period_type)
    if i0 is not None and i1 is not None:
        out["cagr"] = _round(cagr(first["value"], last["value"], i1 - i0))
    if len(pts) >= 2:
        prev = pts[-2]
        out["recentChange"] = {
            "from": prev["period"],
            **calculate_change_rate(last["value"], prev["value"]),
        }
    if period_type in ("M", "Q", "H"):
        ly = same_period_last_year(last["period"])
        prev_year = next((p for p in pts if p["period"] == ly), None)
        if prev_year:
            out["yoy"] = {"from": ly, **calculate_change_rate(last["value"], prev_year["value"])}
    return out


def _pv(p: dict[str, Any]) -> dict[str, Any]:
    return {"period": p["period"], "value": p["value"]}


def _round(v: float | None, nd: int = 3) -> float | None:
    return None if v is None else round(v, nd)


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


class DeriveError(ValueError):
    pass


def parse_expr(expr: str) -> ast.Expression:
    if len(expr) > 500:
        raise DeriveError("수식이 너무 깁니다(500자 이하).")
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, RecursionError, ValueError) as e:
        raise DeriveError(f"수식을 해석할 수 없습니다: {expr}") from e
    for node in ast.walk(tree):
        if not isinstance(
            node,
            (ast.Expression, ast.BinOp, ast.UnaryOp, ast.USub, ast.Name, ast.Load, ast.Constant,
             *_BIN_OPS),
        ):
            raise DeriveError(f"허용되지 않는 수식 요소: {type(node).__name__}")
    return tree


def expr_names(expr: str) -> set[str]:
    return {n.id for n in ast.walk(parse_expr(expr)) if isinstance(n, ast.Name)}


def evaluate(expr: str | ast.Expression, env: Mapping[str, float | None]) -> float | None:
    """사칙연산만 허용. 변수 값이 없거나 0으로 나누거나 결과가 유한하지 않으면 None.
    expr에 parse_expr 결과를 넘기면 다시 파싱하지 않는다."""

    def ev(node: ast.AST) -> float | None:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise DeriveError(f"알 수 없는 series 이름: {node.id}")
            return env[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            v = ev(node.operand)
            return None if v is None else -v
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            if a is None or b is None:
                return None
            if isinstance(node.op, ast.Div) and b == 0:
                return None
            return _BIN_OPS[type(node.op)](a, b)
        raise DeriveError(f"허용되지 않는 수식 요소: {type(node).__name__}")

    tree = parse_expr(expr) if isinstance(expr, str) else expr
    try:
        value = ev(tree)
    except (RecursionError, OverflowError):
        return None
    return value if value is None or math.isfinite(value) else None
