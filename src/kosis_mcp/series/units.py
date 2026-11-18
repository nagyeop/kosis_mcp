"""units — 단위 배수 정규화와 성격(수량·비율·지수) 판정."""

from __future__ import annotations

import re
from typing import Literal, TypedDict

UnitKind = Literal["count", "rate", "index", "other"]

# 긴 접두어부터 매칭 (천만 > 천).
_SCALES: list[tuple[str, float]] = [
    ("십억", 1e9),
    ("천만", 1e7),
    ("백만", 1e6),
    ("십만", 1e5),
    ("천", 1e3),
    ("만", 1e4),
    ("억", 1e8),
    ("조", 1e12),
]
# 배수 접두어로 오인하면 안 되는 단위.
_NO_SCALE = {"천분율", "만분율"}
_RATE_MARKS = ("%", "‰", "퍼센트", "퍼밀", "율", "/", "당", "배")
_INDEX_RE = re.compile(r"지수|=\s*100|기준")


class Unit(TypedDict):
    raw: str | None
    base: str
    scale: float
    kind: UnitKind


def parse_unit(unit: str | None) -> Unit:
    raw = (unit or "").strip()
    base, scale = raw, 1.0
    if raw and raw not in _NO_SCALE and not raw.startswith("조사"):
        for prefix, mult in _SCALES:
            rest = raw[len(prefix) :]
            if raw.startswith(prefix) and rest and not rest.startswith(("분", "율")):
                # '십만명당'·'천명당'은 배수가 아니라 비율의 분모다.
                if any(m in rest for m in ("당", "/", "율")):
                    break
                base, scale = rest.strip(), mult
                break
    if not raw:
        kind: UnitKind = "other"
    elif _INDEX_RE.search(raw):
        kind = "index"
    elif any(m in raw for m in _RATE_MARKS):
        kind = "rate"
    elif base in {"세", "년", "개월", "일", "시간"}:
        kind = "other"
    else:
        kind = "count"
    return {"raw": unit, "base": base, "scale": scale, "kind": kind}


def normalize_value(value: float | None, unit: Unit) -> float | None:
    return None if value is None else value * unit["scale"]


def comparable(a: Unit, b: Unit) -> bool:
    """같은 기준 단위·같은 성격이면 차이·비교 가능. 지수는 원단위가 같아야 한다."""
    if not a["base"] or not b["base"]:
        return False
    if a["kind"] == "index" or b["kind"] == "index":
        return (a["raw"] or "") == (b["raw"] or "")
    return a["base"] == b["base"] and a["kind"] == b["kind"]


# 합산해 전체에 대한 비중을 낼 수 있는 수량 단위. 원(평균·가격)·세(나이) 등은 제외.
_ADDITIVE_BASES = (
    "명", "인", "가구", "세대", "호", "개", "개소", "곳", "건", "대", "척", "동",
    "ha", "km²", "km2", "㎢", "㎡", "m²", "톤", "t", "kg",
)


def additive(unit: Unit) -> bool:
    return unit["kind"] == "count" and unit["base"].replace(" ", "") in _ADDITIVE_BASES
