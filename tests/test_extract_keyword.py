"""extractKeyword regression tests — compound-word false-positive guard."""

from kosis_mcp.data.quick_stats_params import get_quick_stats_param, normalize_keyword_key
from kosis_mcp.tools.quick_stats import extract_district_name, extract_keyword
from kosis_mcp.tools.more_tools import extract_year_count


def test_exact_keyword():
    assert extract_keyword("인구") == "인구"
    assert extract_keyword("GDP") == "GDP"


def test_region_prefix_allowed():
    assert extract_keyword("서울 인구") == "인구"
    assert extract_keyword("서울인구") == "인구"
    assert extract_keyword("광진구 인구") == "인구"
    assert extract_keyword("강원도 인구") == "인구"


def test_particle_and_year_prefix():
    assert extract_keyword("서울의 인구") == "인구"
    assert extract_keyword("2024년 인구") == "인구"
    assert extract_keyword("한국 인구") == "인구"
    assert extract_keyword("전국 실업률") == "실업률"


def test_longer_key_wins():
    assert extract_keyword("노인인구") == "노인인구"
    assert extract_keyword("고령인구비율") == "고령인구비율"


def test_typo_alias():
    assert extract_keyword("출산률") == "출산율"
    assert extract_keyword("저출산") == "출산율"


def test_compound_blocked():
    for q in ["다문화인구", "유소년인구", "외국인 인구 현황", "수도권인구"]:
        assert extract_keyword(q) != "인구", q


def test_youth_unemployment_not_silent():
    # should not map to 실업률 via partial match when compound
    assert extract_keyword("청년실업률") != "실업률"


def test_get_param_alias():
    assert get_quick_stats_param("출산률") is not None
    assert get_quick_stats_param("population") is not None


def test_normalize_key():
    assert normalize_keyword_key("G D P") == "gdp"
    assert normalize_keyword_key("PM 2.5") == "pm25"


def test_extract_year_count():
    assert extract_year_count("지난 10년") == 10
    assert extract_year_count("지난 5년 추세") == 5
    assert extract_year_count("민선 8기") == 4
    assert extract_year_count("작년 대비") == 2
    assert extract_year_count("역대 추이") == 20


def test_district_not_keyword():
    assert extract_district_name("광진구 인구") == "광진구"
    assert extract_district_name("인구") is None
