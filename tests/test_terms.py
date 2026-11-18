"""L2 tests for search-term generation, merge and verify scoring (offline)."""

import pytest

from kosis_mcp.population_search.find import split_subqueries
from kosis_mcp.population_search.terms import analyze, build_search_terms, strip_particle
from kosis_mcp.population_search.verify import query_profile, score_candidate


@pytest.mark.parametrize(
    "query,expected_first",
    [
        ("시도별 인구밀도를 볼 수 있는 통계표 찾아줘", "인구밀도"),
        ("시도별 주민등록 인구", "주민등록 인구"),
        ("시도별 세대수", "세대수"),
        ("2009년에 등록외국인을 국적별로 볼 수 있는 표 찾아줘", "등록외국인 국적별"),
        ("2015년부터 2024년까지 출생아 수를 연도별로 볼 수 있는 표 찾아줘", "출생아수"),
        ("지역마다 사람들이 얼마나 빽빽하게 사는지 볼 수 있는 표 찾아줘", "인구밀도"),
        ("혼자 사는 가구가 몇 가구인지 볼 수 있는 통계표 찾아줘", "1인가구"),
    ],
)
def test_build_search_terms(query, expected_first):
    terms = build_search_terms(query)
    assert terms[0] == expected_first
    assert len(terms) <= 4
    assert all("찾아" not in t and "시도별" not in t for t in terms)


def test_topic_keywords_are_auxiliary_not_replacement():
    terms = build_search_terms("시도별 주민등록 인구")
    assert terms[0] == "주민등록 인구" and "총인구" in terms


def test_analyze_extracts_levels_and_strips_particles():
    a = analyze("2023년 시군구별 결혼이민자를 성별로 볼 수 있는 통계표 찾아줘")
    assert a["levels"] == ["시군구"]
    assert a["core"] == ["결혼이민자", "성별"]
    assert strip_particle("증가") == "증가" and strip_particle("인구가") == "인구"


def test_split_subqueries_rules():
    assert split_subqueries("와이파이 보급률") == ["와이파이 보급률"]
    assert split_subqueries("외국인 주민현황과 다문화가구 현황을 함께 비교하고 싶어") == ["외국인 주민현황", "다문화가구 현황"]
    assert split_subqueries("서울 및 부산 인구") == ["서울 인구", "부산 인구"]


def test_verify_score_level_and_foreign_source():
    profile = query_profile("시도별 세대수")
    sido = {"tableName": "시도별 세대수 현황", "statName": "", "path": "인구 > 주민등록", "searchRank": 3, "endPeriod": "2025"}
    finer = {"tableName": "행정구역(시군구)별 주민등록세대수", "statName": "", "path": "인구 > 주민등록인구현황", "searchRank": 0, "endPeriod": "2025"}
    other_domain = {"tableName": "시도별 월별 세대수 및 가입자 변동현황", "statName": "", "path": "보건 > 건강보험통계", "searchRank": 1, "endPeriod": "2025"}
    # 시군구 표는 시도 합계도 담고, 질의 주제(세대 → 인구)와 분야가 맞는다.
    assert score_candidate(profile, finer) > score_candidate(profile, other_domain)
    assert score_candidate(profile, sido) > score_candidate(profile, other_domain)
    coarse = query_profile("시군구별 세대수")
    assert score_candidate(coarse, sido) < score_candidate(coarse, finer)
    p2 = query_profile("인구 부양비")
    domestic = {"tableName": "부양비", "statName": "장래인구추계", "path": "인구 > 장래인구추계", "searchRank": 2}
    foreign = {"tableName": "부양비", "statName": "", "path": "국제통계연감 > 영토/인구", "searchRank": 0}
    assert score_candidate(p2, domestic) > score_candidate(p2, foreign)


def test_verify_profile_is_deterministic():
    q = "외국인 인구를 성별과 현재 국적별로 볼 수 있는 표 찾아줘"
    assert query_profile(q) == query_profile(q)
    assert query_profile(q)["tokens"][:3] == ["외국인", "인구", "성별"]


async def test_merge_interleaves_terms_and_keys_count():
    from kosis_mcp.tools.more_tools import _merge_search_results

    keys: list[dict] = []

    class FakeCache:
        def _generate_key(self, prefix, params):
            return str(params)

        async def _get(self, key):
            return None

        async def get_search_results(self, params, fetcher):
            keys.append(params)
            t = params["q"]
            return [{"ORG_ID": "101", "TBL_ID": f"{t}{i}", "TBL_NM": t} for i in range(3)]

    rows, _ = await _merge_search_results(FakeCache(), None, ["A", "B"], None, "RANK", 4, {})
    assert [r["tableId"] for r in rows] == ["A0", "B0", "A1", "B1"]
    assert [r["searchRank"] for r in rows] == [0, 0, 1, 1]
    assert all(k["count"] == 20 for k in keys)
