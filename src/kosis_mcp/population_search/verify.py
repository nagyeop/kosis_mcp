"""batch_verify_table_candidates — 후보 표의 질의 적합도 점수(연속값, 결정적).

점수 = 핵심어 일치(0~1) + 행정 수준 일치(±) + 검색 순위 보너스 + 최신성(±) + 범위 밖 출처 감점 + 메타 힌트.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from kosis_mcp.population_search.categories import category_of
from kosis_mcp.population_search.terms import CONCEPTS, analyze
from kosis_mcp.utils.query_parser import parse_query
from kosis_mcp.tools.get_table_info import get_table_info
from kosis_mcp.utils.concurrency import map_with_concurrency

_VERIFY_CONCURRENCY = 5

# 질의의 수준어 → 표 이름에서 찾을 표지
_LEVEL_MARKS = {
    "sido": ("시도", "시·도", "광역"),
    "sigungu": ("시군구", "시·군·구", "시/군/구", "시군", "자치구", "구별"),
    "eupmyeondong": ("읍면동", "동읍면", "읍·면·동"),
}
_LEVEL_ORDER = {"sido": 0, "sigungu": 1, "eupmyeondong": 2}
_QUERY_LEVEL = {
    "시도": "sido", "시·도": "sido", "광역": "sido",
    "시군구": "sigungu", "시·군·구": "sigungu", "시군": "sigungu", "군구": "sigungu", "자치구": "sigungu", "구": "sigungu",
    "읍면동": "eupmyeondong", "동읍면": "eupmyeondong", "읍면": "eupmyeondong",
}
# 질의 주제(parse_query topics) → 기대 분야(MT_ZTITLE 최상위). 일치하면 가점.
_TOPIC_CATEGORIES = {
    "population": {"인구"},
    "economy": {"국민계정", "물가", "경제일반ㆍ경기", "무역ㆍ국제수지", "금융"},
    "employment": {"노동", "임금"},
    "housing": {"주거", "국토이용"},
    "education": {"교육ㆍ훈련"},
    "health": {"보건"},
    "environment": {"환경"},
    "transport": {"교통ㆍ물류"},
    "social": {"범죄ㆍ안전", "복지", "사회일반"},
}
_FOREIGN_SOURCE = re.compile(r"국제통계|아주지역|World Bank|OECD|UN |국제기구")
_FOREIGN_QUERY = re.compile(r"국제|세계|해외|OECD|외국과|각국|국가별")


def query_profile(query: str) -> dict[str, Any]:
    a = analyze(query)
    tokens = list(dict.fromkeys([*(c for p, c in CONCEPTS if p.search(query)), *a["core"]]))
    levels = list(dict.fromkeys(_QUERY_LEVEL[lv] for lv in a["levels"] if lv in _QUERY_LEVEL))
    categories = set().union(*(_TOPIC_CATEGORIES.get(t, set()) for t in parse_query(query)["topics"]))
    return {
        "tokens": tokens,
        "levels": levels,
        "foreign": bool(_FOREIGN_QUERY.search(query)),
        "categories": sorted(categories),
    }


def _token_hit(token: str, name: str) -> float:
    if token in name:
        return 1.0
    # '국적별' vs '국적', '등록외국인' vs '외국인' 같은 부분 일치
    if len(token) >= 3 and (token[:-1] in name or token[1:] in name):
        return 0.5
    if " " in token:
        parts = token.split()
        return sum(p in name for p in parts) / len(parts)
    return 0.0


def score_candidate(profile: dict[str, Any], cand: dict[str, Any], hint: str = "") -> float:
    name = " ".join(str(cand.get(k) or "") for k in ("tableName", "statName"))
    tokens = profile["tokens"]
    base = sum(_token_hit(t, name) for t in tokens) / max(len(tokens), 1)

    level_adj = 0.0
    if profile["levels"]:
        has = {lv for lv, marks in _LEVEL_MARKS.items() if any(m in name for m in marks)}
        want = min(_LEVEL_ORDER[lv] for lv in profile["levels"])
        if has & set(profile["levels"]):
            level_adj = 0.15
        elif has and max(_LEVEL_ORDER[lv] for lv in has) > want:
            level_adj = 0.05  # 더 세밀한 표는 상위 수준(시도 합계 등)도 담는다
        elif has:
            level_adj = -0.1  # 요청보다 거친 수준만 있는 표

    rank = cand.get("searchRank")
    rank_bonus = 0.1 * (1 - min(int(rank), 20) / 20) if isinstance(rank, int) else 0.0

    fresh_adj = 0.0
    end = str(cand.get("endPeriod") or "")[:4]
    if end.isdigit():
        gap = date.today().year - int(end)
        if gap >= 6:
            fresh_adj = -0.1  # 갱신이 끊긴 계열
        elif 0 <= gap <= 2:
            fresh_adj = 0.05

    path = str(cand.get("path") or "")
    foreign_adj = -0.2 if _FOREIGN_SOURCE.search(path + name) and not profile["foreign"] else 0.0
    hint_adj = 0.05 * sum(1 for t in tokens[:3] if t and t in hint)
    topic_adj = 0.0
    if profile.get("categories"):
        cat = category_of({"path": path})
        if cat:
            topic_adj = 0.15 if cat in profile["categories"] else -0.05
    return round(base + level_adj + rank_bonus + fresh_adj + foreign_adj + hint_adj + topic_adj, 4)


async def _verify_one(profile: dict[str, Any], candidate: dict[str, Any], _i: int) -> dict[str, Any]:
    org_id = candidate.get("orgId") or ""
    table_id = candidate.get("tableId") or ""
    filter_kw = " ".join(profile["tokens"][:3]) or None  # 결정적 순서
    info = await get_table_info(org_id, table_id, filter=filter_kw, sampleSize=5)
    passed = bool(info.get("success") and info.get("groups"))
    score = score_candidate(profile, candidate, (info.get("hint") or "") if passed else "")
    return {
        "orgId": org_id,
        "tableId": table_id,
        "tableName": candidate.get("tableName") or "",
        "score": score,
        "passed": passed,
    }


async def batch_verify_table_candidates(
    query: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        return {"success": True, "query": query, "verified": []}
    profile = query_profile(query)
    verified = await map_with_concurrency(
        candidates[:10],
        lambda c, i: _verify_one(profile, c, i),
        _VERIFY_CONCURRENCY,
    )
    # 동점은 검색 순서를 유지한다(안정 정렬).
    verified.sort(key=lambda v: v["score"], reverse=True)
    return {"success": True, "query": query, "verified": verified}
