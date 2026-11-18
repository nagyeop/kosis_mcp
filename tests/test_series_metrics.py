"""L2 tests for series units / metrics / align (pure functions)."""

import pytest

from kosis_mcp.series.align import choose_targets, pick_point
from kosis_mcp.series.metrics import (
    DeriveError,
    cagr,
    evaluate,
    period_index,
    rank,
    trend_stats,
)
from kosis_mcp.series.units import comparable, normalize_value, parse_unit


def test_parse_unit_scale_and_kind():
    assert parse_unit("천명") == {"raw": "천명", "base": "명", "scale": 1e3, "kind": "count"}
    assert parse_unit("백만원")["scale"] == 1e6
    assert parse_unit("%")["kind"] == "rate"
    assert parse_unit("명/km²")["kind"] == "rate"
    assert parse_unit("2020=100")["kind"] == "index"
    assert parse_unit("천분율")["scale"] == 1
    assert normalize_value(1.5, parse_unit("천명")) == 1500


def test_comparable_units():
    assert comparable(parse_unit("천명"), parse_unit("명"))
    assert not comparable(parse_unit("명"), parse_unit("%"))
    assert not comparable(parse_unit("명"), parse_unit("세대"))
    assert not comparable(parse_unit("2015=100"), parse_unit("2020=100"))


def test_rank_handles_ties_and_none():
    assert rank({"a": 3, "b": 5, "c": 5, "d": None, "e": 1}) == {"b": 1, "c": 1, "a": 3, "e": 4}
    assert rank({"a": 3, "b": 5}, descending=False) == {"a": 1, "b": 2}


def test_period_index_and_cagr():
    assert period_index("2024", "Y") == 2024
    assert period_index("202407", "M") == pytest.approx(2024.5)
    assert period_index("202503", "Q") == pytest.approx(2025.5)
    assert cagr(100, 121, 2) == pytest.approx(10)
    assert cagr(0, 10, 2) is None


def test_trend_stats_monthly_yoy():
    pts = [{"period": f"2025{m:02d}", "value": 100 + m} for m in range(1, 13)]
    pts.append({"period": "202601", "value": 120})
    out = trend_stats(pts, "M")
    assert out["end"] == {"period": "202601", "value": 120}
    assert out["yoy"]["from"] == "202501"
    assert out["recentChange"]["from"] == "202512"
    assert out["max"] == {"period": "202601", "value": 120}


def test_evaluate_safe_arithmetic():
    assert evaluate("s1 / s2", {"s1": 10, "s2": 4}) == 2.5
    assert evaluate("(인구 - 가구) * 2", {"인구": 5, "가구": 3}) == 4
    assert evaluate("s1 / s2", {"s1": 10, "s2": 0}) is None
    assert evaluate("s1 / s2", {"s1": None, "s2": 1}) is None
    with pytest.raises(DeriveError):
        evaluate("__import__('os')", {})
    with pytest.raises(DeriveError):
        evaluate("s3 + 1", {"s1": 1})


def _series(points):
    return {"points": [{"period": p, "value": v} for p, v in points]}


def test_pick_point_year_from_monthly_prefers_year_end():
    s = _series([("202511", 1), ("202512", 2), ("202601", 3)])
    assert pick_point(s, "M", "2025") == ({"period": "202512", "value": 2}, None)
    point, note = pick_point(s, "M", "2026")
    assert point["period"] == "202601" and "연말값" in note
    assert pick_point(s, "M", None)[0]["period"] == "202601"


def test_choose_targets_common_latest_same_type():
    a = {"periodType": "Y", "series": [_series([("2023", 1), ("2024", 1), ("2025", 1)])]}
    b = {"periodType": "Y", "series": [_series([("2022", 1), ("2023", 1)])]}  # GRDP 시차
    targets, _ = choose_targets([a, b])
    assert targets == ["2023", "2023"]


def test_choose_targets_mixed_frequency_uses_year():
    m = {"periodType": "M", "series": [_series([("202512", 1), ("202609", 1)])]}
    y = {"periodType": "Y", "series": [_series([("2024", 1), ("2025", 1)])]}
    targets, warnings = choose_targets([m, y])
    assert targets == ["2025", "2025"]
    assert warnings


def test_choose_targets_explicit_and_latest_each():
    m = {"periodType": "M", "series": [_series([("202512", 1)])]}
    y = {"periodType": "Y", "series": [_series([("2025", 1)])]}
    assert choose_targets([m, y], period="202512")[0] == ["202512", "2025"]
    assert choose_targets([m, y], mode="latest_each")[0] == [None, None]


def test_rate_units_are_not_scaled():
    from kosis_mcp.series.units import additive

    assert parse_unit("십만명당")["scale"] == 1
    assert parse_unit("천명당")["kind"] == "rate"
    assert not additive(parse_unit("만원"))
    assert additive(parse_unit("천명")) and additive(parse_unit("가구"))
    assert not comparable(parse_unit(""), parse_unit(""))


def test_normalize_period_formats():
    from kosis_mcp.series.periods import PeriodError, normalize_period

    assert normalize_period("2025.06", "M") == "202506"
    assert normalize_period("2025년 6월", "M") == "202506"
    assert normalize_period("202509", "Q") == "202503"
    assert normalize_period("202503", "Q") == "202503"  # KOSIS 분기 코드 그대로
    assert normalize_period("2025 2/4", "Q") == "202502"
    assert normalize_period("2025년 하반기", "H") == "202502"
    assert normalize_period("202509", "Y") == "2025"
    assert normalize_period("2025", "M") == "2025"  # 연도 = 그 해 전체
    with pytest.raises(PeriodError):
        normalize_period("2025.06", "D")
    with pytest.raises(PeriodError):
        normalize_period("작년", "Y")


def test_period_params_windows():
    from kosis_mcp.series.fetch import period_params

    assert period_params("Y", start="2015") == {"startPrdDe": "2015", "endPrdDe": "9999"}
    assert period_params("M", start="2015", end="2024") == {"startPrdDe": "201501", "endPrdDe": "202412"}
    assert period_params("M", end="2025.12", recent=12) == {"startPrdDe": "202501", "endPrdDe": "202512"}
    assert period_params("Q", period="202509") == {"startPrdDe": "202503", "endPrdDe": "202503"}
    assert period_params("H", period="2025") == {"startPrdDe": "202501", "endPrdDe": "202502"}


def test_choose_targets_skips_empty_groups():
    a = {"periodType": "M", "series": [_series([("202512", 1), ("202609", 1)])], "label": "a"}
    empty = {"periodType": "Y", "series": [], "label": "b"}
    c = {"periodType": "M", "series": [_series([("202609", 1)])], "label": "c"}
    targets, warnings = choose_targets([a, empty, c])
    assert targets == ["202609", None, "202609"]
    assert any("b" in w for w in warnings)


def test_evaluate_guards_overflow():
    assert evaluate("s1 * s1", {"s1": 1e308}) is None
