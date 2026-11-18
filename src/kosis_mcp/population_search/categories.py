"""KOSIS 주제별(MT_ZTITLE) 최상위 29개 분야."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

# MT_ZTITLE 최상위 LIST_ID → 분야명 (V 지역통계는 뷰 성격이라 제외)
CATEGORY_LIST_IDS: dict[str, str] = {
    "인구": "A",
    "사회일반": "B",
    "범죄ㆍ안전": "C",
    "노동": "D",
    "소득ㆍ소비ㆍ자산": "E",
    "보건": "F",
    "복지": "G",
    "교육ㆍ훈련": "H1",
    "문화ㆍ여가": "H2",
    "주거": "I1",
    "국토이용": "I2",
    "경제일반ㆍ경기": "J1",
    "기업경영": "J2",
    "농림": "K1",
    "수산": "K2",
    "광업ㆍ제조업": "L",
    "건설": "M1",
    "교통ㆍ물류": "M2",
    "정보통신": "N1",
    "과학ㆍ기술": "N2",
    "도소매ㆍ서비스": "O",
    "임금": "P1",
    "물가": "P2",
    "국민계정": "Q",
    "정부ㆍ재정": "R",
    "금융": "S1",
    "무역ㆍ국제수지": "S2",
    "환경": "T",
    "에너지": "U",
}

Category = Literal[
    "인구",
    "사회일반",
    "범죄ㆍ안전",
    "노동",
    "소득ㆍ소비ㆍ자산",
    "보건",
    "복지",
    "교육ㆍ훈련",
    "문화ㆍ여가",
    "주거",
    "국토이용",
    "경제일반ㆍ경기",
    "기업경영",
    "농림",
    "수산",
    "광업ㆍ제조업",
    "건설",
    "교통ㆍ물류",
    "정보통신",
    "과학ㆍ기술",
    "도소매ㆍ서비스",
    "임금",
    "물가",
    "국민계정",
    "정부ㆍ재정",
    "금융",
    "무역ㆍ국제수지",
    "환경",
    "에너지",
]

POPULATION = "인구"
PATH_SEP = " > "


def category_of(row: dict[str, Any]) -> str | None:
    """Category from a search row's MT_ATITLE path (any view whose path names one)."""
    path = row.get("path") or row.get("MT_ATITLE") or ""
    for part in str(path).split(PATH_SEP):
        if part.strip() in CATEGORY_LIST_IDS:
            return part.strip()
    return None


def category_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(c for c in (category_of(r) for r in rows) if c)
    return dict(counts.most_common())
