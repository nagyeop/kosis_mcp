"""terms — 자연어 질의 → KOSIS 검색어.

KOSIS 통계표 검색은 긴 문장에 '데이터 없음'을 돌려주고, '시도별' 같은 수준어나 조사가 붙은 어절에
엉뚱한 표를 올린다. 그래서 핵심 명사만 남겨 짧은 검색어 여러 개를 만든다. 수준어·연도는 검색어에서
빼고 검증 단계(verify)에서 쓴다. 주제 사전(parse_query)은 질의를 대체하지 않고 보조 검색어로 붙인다.
"""

from __future__ import annotations

import re
from typing import Any

from kosis_mcp.utils.query_parser import parse_query

MAX_TERMS = 4

_PUNCT = re.compile(r"[?!.,·'\"“”‘’()\[\]]")
# 행정 수준·시간 축 표현(검색어에서 제외, 검증에 사용)
LEVEL_RE = re.compile(
    r"^(?P<lv>시도|시·도|광역|시군구|시·군·구|시군|군구|자치구|구|읍면동|동읍면|읍면|행정구역|지역|전국)"
    r"(별|마다|단위)?(로|의|로는)?$"
)
_TIME_RE = re.compile(r"^(\d{4}년?|\d{4}~\d{4}년?|연도|월|분기|반기|연간|월간|연)(별|부터|까지|에|의|과|와|도)?(로)?$")
_STOP = {
    "통계표", "통계", "표", "자료", "데이터", "정보", "현황을", "수치", "각", "모든", "전체", "기준", "기준의",
    "기준으로", "동일한", "같은", "하나의", "어떤", "무슨", "있는", "있어", "있나요", "있을까", "있을까요", "볼", "수",
    "찾아줘", "찾아", "줘", "주세요", "알려줘", "알려", "보여줘", "확인", "확인할", "비교", "비교할", "비교하고",
    "알고", "싶어", "싶어요", "싶은데", "궁금해", "궁금합니다", "같이", "함께", "그리고", "및", "또는", "나눠",
    "나눠서", "나뉘는지", "따라", "따른", "어떻게", "얼마나", "몇", "명", "명인지", "얼마", "되는지", "인지", "현재",
    "최근", "최신", "올해", "작년", "지난", "제외해줘", "제외", "빼고", "말고", "표는", "표가", "표를", "표로",
    "다른", "사람", "사람들", "들어온", "온", "한", "해", "추이", "현황", "구성", "보고", "보기",
}
# 끝 조사 (길이 순). 떼고 남은 길이가 2 이상일 때만.
_PARTICLES = (
    "에서의", "에서는", "에서", "으로는", "으로", "별로", "에게", "이랑", "까지", "부터", "보다", "처럼",
    "와의", "과의", "들의", "들을", "들이", "을", "를", "의", "은", "는", "이", "가", "에", "와", "과", "로",
)
# 조사처럼 보이는 글자로 끝나는 명사(그대로 둔다)
_KEEP = {
    "증가", "물가", "주가", "국가", "지가", "평가", "단가", "원가", "시가", "나이", "차이", "아이", "어린이",
    "도로", "고속도로", "경로", "진로", "항로", "철도로",
}
# 바꿔 말한 표현 → 통계 용어 (앞쪽 검색어로 넣는다)
CONCEPTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"빽빽|밀집|북적"), "인구밀도"),
    (re.compile(r"태어난|태어나|아기|신생아"), "출생아수"),
    (re.compile(r"이사|들어온|이주|전입|전출"), "인구이동"),
    (re.compile(r"결혼해서.*(외국인|이민)|결혼\s*이민"), "결혼이민자"),
    (re.compile(r"혼자\s*사는|나\s*홀로|1인\s*가구"), "1인가구"),
    (re.compile(r"돌아가신|사망한|죽은"), "사망자수"),
    (re.compile(r"나이(대|별)?|연령대"), "연령별 인구"),
    (re.compile(r"늙|고령|노인|노년"), "고령인구"),
)
_PREDICATE_END = ("는지", "인지", "하는", "되는", "사는", "있는", "없는", "하고", "해서", "하게", "된", "난", "온", "한")


def strip_particle(token: str) -> str:
    if token in _KEEP:
        return token
    for p in _PARTICLES:
        if not token.endswith(p) or len(token) == len(p):
            continue
        stem = token[: -len(p)]
        # '별로'는 '…별'로 남긴다(성별로 → 성별).
        if p == "별로":
            return stem + "별"
        if len(stem) >= 2 or stem == "수":
            return stem
    return token


def analyze(query: str) -> dict[str, Any]:
    """→ {core: 핵심어, levels: 수준어, times: 시간어}."""
    core: list[str] = []
    levels: list[str] = []
    times: list[str] = []
    for raw in _PUNCT.sub(" ", query).split():
        tok = raw.strip()
        if not tok:
            continue
        if m := LEVEL_RE.match(tok):
            levels.append(m.group("lv"))
            continue
        if _TIME_RE.match(tok):
            times.append(tok)
            continue
        base = strip_particle(tok)
        if base == "수" and tok != "수" and core:
            # '출생아 수를' → '출생아수' ('볼 수 있는'의 '수'는 그대로 버린다)
            core[-1] = core[-1] + "수"
            continue
        if tok in _STOP or base in _STOP:
            continue
        if LEVEL_RE.match(base):
            levels.append(LEVEL_RE.match(base).group("lv"))  # type: ignore[union-attr]
            continue
        if base not in _KEEP and base.endswith(_PREDICATE_END) and len(base) <= 4:
            continue
        if len(base) < 2 and not base.isdigit():
            continue
        if base not in core:
            core.append(base)
    return {"core": core, "levels": levels, "times": times}


def build_search_terms(query: str, *, max_terms: int = MAX_TERMS) -> list[str]:
    a = analyze(query)
    core = a["core"]
    terms: list[str] = [concept for pat, concept in CONCEPTS if pat.search(query)][:2]
    if core:
        terms.append(" ".join(core[:3]))
        for i in range(len(core) - 1):
            terms.append(f"{core[i]} {core[i + 1]}")
        if len(core) > 1:
            terms.append(max(core, key=len))
    parsed = parse_query(query)
    if parsed["topics"]:
        terms.extend(parsed["keywords"][:2])
    if not terms:
        terms.append(query.strip())
    return list(dict.fromkeys(t for t in terms if t))[:max_terms]
