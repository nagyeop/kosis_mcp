"""Common classification axes (12 areas) aligned with VDB table metadata."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from typing_extensions import TypedDict

from pydantic import Field

from kosis_mcp.utils.query_parser import REGION_CODES, REGION_NAMES

AxisCategory = Literal[
    "region",
    "sex",
    "age",
    "time",
    "marital",
    "education",
    "housing",
    "industry_occupation",
    "business",
    "response",
    "continent",
    "agri",
]
AxisMode = Literal["by", "where"]


class AxisSpec(TypedDict, total=False):
    category: Annotated[AxisCategory, Field(description="공통 분류 영역")]
    mode: Annotated[
        AxisMode,
        Field(description="by=그 분류로 나뉜 표(~별) · where=특정 항목값을 가진 표"),
    ]
    level: Annotated[
        str | None,
        Field(
            description=(
                "region: sido|sigungu|eupmyeondong|dong_eup_myeon|si_gun · "
                "age: 1y|3y|5y|10y|mixed|other · time: year|half|quarter|month · "
                "education: school_type|attainment · "
                "business: employee_size|firm_size|firm_type|employment_status · "
                "industry_occupation: industry_major|industry_mid|industry_minor|"
                "occupation_major|occupation_mid|occupation_minor · "
                "response: satisfaction|yes_no|degree"
            )
        ),
    ]
    values: Annotated[
        list[str] | None,
        Field(description="where 항목값 (예: 서울, 65세 이상, 여자)"),
    ]


_LEVELS: dict[str, tuple[str, ...]] = {
    "region": ("sido", "sigungu", "eupmyeondong", "dong_eup_myeon", "si_gun"),
    "age": ("1y", "3y", "5y", "10y", "mixed", "other"),
    "time": ("year", "half", "quarter", "month"),
    "education": ("school_type", "attainment"),
    "business": ("employee_size", "firm_size", "firm_type", "employment_status"),
    "industry_occupation": (
        "industry_major",
        "industry_mid",
        "industry_minor",
        "occupation_major",
        "occupation_mid",
        "occupation_minor",
    ),
    "response": ("satisfaction", "yes_no", "degree"),
}

_VALUE_ALIASES: dict[str, dict[str, str]] = {
    "sex": {"남성": "남자", "남": "남자", "여성": "여자", "여": "여자"},
    "marital": {"유배우": "배우자 있음", "유배우자": "배우자 있음"},
}

_BY_LABELS: dict[str, str] = {
    "region": "지역별",
    "sex": "성별",
    "age": "연령별",
    "time": "시점별",
    "marital": "혼인상태별",
    "education": "교육별",
    "housing": "거처종류별",
    "industry_occupation": "산업별",
    "business": "규모별",
    "response": "응답별",
    "continent": "대륙별",
    "agri": "전겸업별",
}

_LEVEL_LABELS: dict[str, str] = {
    "sido": "시도별",
    "sigungu": "시군구별",
    "eupmyeondong": "읍면동별",
    "dong_eup_myeon": "동읍면부별",
    "si_gun": "시군부별",
    "1y": "각세별",
    "3y": "3세별",
    "5y": "5세별",
    "10y": "10세별",
    "year": "연도별",
    "half": "반기별",
    "quarter": "분기별",
    "month": "월별",
    "school_type": "학교급별",
    "attainment": "교육정도별",
    "employee_size": "종사자규모별",
    "firm_size": "기업규모별",
    "firm_type": "조직형태별",
    "employment_status": "종사상지위별",
    "industry_major": "산업별",
    "industry_mid": "산업중분류별",
    "industry_minor": "산업소분류별",
    "occupation_major": "직업별",
    "occupation_mid": "직업중분류별",
    "occupation_minor": "직업소분류별",
    "satisfaction": "만족도",
}

# (pattern, category, level) — first hit per category wins.
_BY_PATTERNS: tuple[tuple[re.Pattern[str], str, str | None], ...] = (
    (re.compile(r"읍.?면.?동|법정동|행정동"), "region", "eupmyeondong"),
    (re.compile(r"동.?읍.?면부|동부.?읍부.?면부"), "region", "dong_eup_myeon"),
    (re.compile(r"시부.?군부"), "region", "si_gun"),
    (re.compile(r"시군구|자치구|구별|군별"), "region", "sigungu"),
    (re.compile(r"시도별|광역|17개\s*시도"), "region", "sido"),
    (re.compile(r"지역별"), "region", None),
    (re.compile(r"성별|남녀별"), "sex", None),
    (re.compile(r"각세별|(?<!\d)1세\s*(별|단위)"), "age", "1y"),
    (re.compile(r"(?<!\d)3세\s*(별|단위|연령|계급)"), "age", "3y"),
    (re.compile(r"(?<!\d)5세\s*(별|단위|연령|계급)"), "age", "5y"),
    (re.compile(r"(?<!\d)10세\s*(별|단위|연령|계급)|연령대별"), "age", "10y"),
    (re.compile(r"연령별|나이별|연령\s*구간"), "age", None),
    (re.compile(r"월별"), "time", "month"),
    (re.compile(r"분기별"), "time", "quarter"),
    (re.compile(r"반기별"), "time", "half"),
    (re.compile(r"연도별|연별|년도별"), "time", "year"),
    (re.compile(r"혼인\s*상태"), "marital", None),
    (re.compile(r"교육\s*정도|학력별"), "education", "attainment"),
    (re.compile(r"학교\s*(급|종류)"), "education", "school_type"),
    (re.compile(r"거처\s*종류|주택\s*종류|주거\s*형태"), "housing", None),
    (re.compile(r"종사상\s*지위"), "business", "employment_status"),
    (re.compile(r"산업별"), "industry_occupation", "industry_major"),
    (re.compile(r"직업별"), "industry_occupation", "occupation_major"),
    (re.compile(r"대륙별"), "continent", None),
)

_WHERE_PATTERNS: tuple[tuple[re.Pattern[str], str, str | None], ...] = (
    (re.compile(r"남성|남자"), "sex", None),
    (re.compile(r"여성|여자"), "sex", None),
    (re.compile(r"미혼|유배우|배우자\s*있음|사별|이혼"), "marital", None),
    (re.compile(r"초졸|중졸|고졸|전문대졸|대졸"), "education", "attainment"),
    (
        re.compile(r"아파트|단독주택|연립주택|다세대주택|오피스텔"),
        "housing",
        None,
    ),
)

_AGE_BOUND = re.compile(r"(\d+)\s*세\s*(이상|이하|미만|초과)")
_AGE_RANGE = re.compile(r"(\d+)\s*[~\-]\s*(\d+)\s*세")


def _normalize_value(category: str, value: str) -> str:
    value = value.strip()
    if category == "region":
        code = REGION_CODES.get(value)
        return REGION_NAMES.get(code, value) if code else value
    return _VALUE_ALIASES.get(category, {}).get(value, value)


def normalize_axes(axes: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Validate levels, canonicalize values, merge duplicate (category, mode)."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for axis in axes or []:
        category = axis.get("category")
        if category not in _BY_LABELS:
            continue
        mode = axis.get("mode") or ("where" if axis.get("values") else "by")
        level = axis.get("level")
        if level not in _LEVELS.get(category, ()):
            level = None
        values = [
            _normalize_value(category, v) for v in axis.get("values") or [] if v
        ]
        key = (category, mode)
        cur = merged.setdefault(key, {"category": category, "mode": mode})
        if level and not cur.get("level"):
            cur["level"] = level
        if values:
            cur["values"] = list(dict.fromkeys([*cur.get("values", []), *values]))
    return list(merged.values())


def extract_axes(query: str) -> list[dict[str, Any]]:
    """Rule-based axis extraction from a natural-language query."""
    axes: list[dict[str, Any]] = []
    seen_by: set[str] = set()
    for pattern, category, level in _BY_PATTERNS:
        if category in seen_by or not pattern.search(query):
            continue
        seen_by.add(category)
        axes.append({"category": category, "mode": "by", "level": level})

    regions = [
        REGION_NAMES.get(code, name)
        for name, code in REGION_CODES.items()
        if name in query and code != "00"
    ]
    if regions:
        axes.append({"category": "region", "mode": "where", "values": regions})

    for pattern, category, level in _WHERE_PATTERNS:
        hits = pattern.findall(query)
        if hits:
            axes.append(
                {"category": category, "mode": "where", "level": level, "values": hits}
            )

    ages = [f"{n}세 {op}" for n, op in _AGE_BOUND.findall(query)]
    ages += [f"{a}~{b}세" for a, b in _AGE_RANGE.findall(query)]
    if ages:
        axes.append({"category": "age", "mode": "where", "values": ages})

    return normalize_axes(axes)


def merge_axes(
    extracted: list[dict[str, Any]], explicit: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Explicit axes override extracted ones per (category, mode)."""
    explicit_norm = normalize_axes(explicit)
    keys = {(a["category"], a["mode"]) for a in explicit_norm}
    kept = [a for a in extracted if (a["category"], a["mode"]) not in keys]
    return kept + explicit_norm


def axes_to_terms(axes: list[dict[str, Any]]) -> list[str]:
    """Interim KOSIS API keywords until the VDB axis filter is wired."""
    terms: list[str] = []
    for axis in axes:
        if axis["mode"] == "by":
            level = axis.get("level")
            terms.append(_LEVEL_LABELS.get(level or "", _BY_LABELS[axis["category"]]))
        else:
            terms.extend(axis.get("values") or [])
    return list(dict.fromkeys(terms))


def build_axis_filter(axes: list[dict[str, Any]]) -> dict[str, Any]:
    """VDB metadata spec — axes boost ranking, never hard-filter."""
    return {"boost": axes}
