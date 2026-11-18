"""periods — 사용자 시점 입력을 표 주기(prdSe)의 PRD_DE 형식으로 정규화한다."""

from __future__ import annotations

import re
from datetime import date, timedelta

# 주기별 연간 시점 수와 하위 코드 자릿수 (KOSIS PRD_DE: M 202509, Q 202503=3분기, H 202502=하반기).
PER_YEAR = {"M": 12, "Q": 4, "H": 2}
_FAR_END = {"Y": "9999", "M": "999912", "Q": "999904", "H": "999902", "D": "99991231"}

_YEAR = re.compile(r"^(\d{4})\s*년?$")
_YM = re.compile(r"^(\d{4})\s*(?:[.\-/]|년)?\s*(\d{1,2})\s*월?$")
_QUARTER = re.compile(r"^(\d{4})\s*(?:년)?\s*(?:[Qq]\s*(\d)|(\d)\s*/\s*4|(\d)\s*분기)$")
_HALF = re.compile(r"^(\d{4})\s*(?:년)?\s*(?:[Hh]\s*(\d)|(\d)\s*/\s*2|(상|하)\s*반기)$")
_DAY = re.compile(r"^(\d{4})[.\-/]?(\d{2})[.\-/]?(\d{2})$")


class PeriodError(ValueError):
    pass


def _parse(p: str) -> tuple[str, int, int | None, str]:
    """→ (year, sub, None|day, kind). kind: year|month|quarter|half|day|code6."""
    s = p.strip()
    if m := _YEAR.match(s):
        return m.group(1), 0, None, "year"
    if m := _QUARTER.match(s):
        return m.group(1), int(next(g for g in m.groups()[1:] if g)), None, "quarter"
    if m := _HALF.match(s):
        g = [x for x in m.groups()[1:] if x][0]
        return m.group(1), {"상": 1, "하": 2}.get(g, int(g) if g.isdigit() else 0), None, "half"
    if m := _DAY.match(s):
        return m.group(1), int(m.group(2)), int(m.group(3)), "day"
    if s.isdigit() and len(s) == 6:
        return s[:4], int(s[4:]), None, "code6"
    if m := _YM.match(s):
        return m.group(1), int(m.group(2)), None, "month"
    raise PeriodError(f"시점 형식을 해석할 수 없습니다: {p!r} (예: 2025, 202509, 2025.09, 2025 3/4, 2025년 상반기)")


def normalize_period(p: str, period_type: str) -> str:
    """연도만 주어지면 4자리 연도를 그대로 돌려준다(그 해 전체를 뜻함)."""
    year, sub, day, kind = _parse(p)
    if kind == "year" or period_type in ("Y", "F", "IR"):
        if period_type in ("F", "IR") and kind not in ("year", "code6"):
            raise PeriodError(f"{period_type} 주기 표에는 연도(YYYY)로 지정하세요: {p!r}")
        return year
    per = PER_YEAR.get(period_type)
    if period_type == "D":
        if kind != "day":
            raise PeriodError(f"일(D) 주기 표에는 YYYYMMDD로 지정하세요: {p!r}")
        return f"{year}{sub:02d}{day:02d}"
    if per is None:
        raise PeriodError(f"알 수 없는 주기: {period_type}")
    if kind == "day":
        kind = "month"
    # code6: 표 주기의 코드 범위 안이면 그대로(KOSIS PRD_DE), 넘으면 월로 본다.
    if kind == "code6":
        kind = "native" if 1 <= sub <= per else "month"
    if kind == "month":
        if not 1 <= sub <= 12:
            raise PeriodError(f"월은 1~12여야 합니다: {p!r}")
        sub = (sub - 1) * per // 12 + 1
    elif kind == "quarter":
        if not 1 <= sub <= 4:
            raise PeriodError(f"분기는 1~4여야 합니다: {p!r}")
        sub = {12: sub * 3, 4: sub, 2: (sub + 1) // 2}[per]
    elif kind == "half":
        if not 1 <= sub <= 2:
            raise PeriodError(f"반기는 1~2여야 합니다: {p!r}")
        sub = {12: sub * 6, 4: sub * 2, 2: sub}[per]
    return f"{year}{sub:02d}"


def year_bounds(year: str, period_type: str) -> tuple[str, str]:
    per = PER_YEAR.get(period_type)
    if per:
        return f"{year}01", f"{year}{per:02d}"
    if period_type == "D":
        return f"{year}0101", f"{year}1231"
    return year, year


def far_end(period_type: str) -> str:
    return _FAR_END.get(period_type, "9999")


def shift_back(period: str, period_type: str, steps: int) -> str | None:
    """period에서 steps 시점 이전(포함 구간의 시작). 지원하지 않는 주기면 None."""
    if steps <= 0:
        return period
    if period_type in ("Y", "F", "IR"):
        return str(int(period[:4]) - steps)
    per = PER_YEAR.get(period_type)
    if per:
        idx = int(period[:4]) * per + int(period[4:]) - 1 - steps
        return f"{idx // per}{idx % per + 1:02d}"
    if period_type == "D":
        d = date(int(period[:4]), int(period[4:6]), int(period[6:8])) - timedelta(days=steps)
        return d.strftime("%Y%m%d")
    return None
