"""L2 tests for keyword layer (quick_trend / quick_rank / compare_regions) on the series core."""

import pytest

from kosis_mcp.data.quick_stats_params import get_quick_stats_param
from kosis_mcp.series import keyword as keyword_mod
from kosis_mcp.series.keyword import param_spec
from kosis_mcp.tools import more_tools, series_tools


def test_param_spec_region_level_1_and_2():
    spec, name = param_spec(get_quick_stats_param("인구"), region="부산")
    assert spec["codes"] == {"itmId": "T20", "objL1": "26"} and name == "부산"
    spec, _ = param_spec(get_quick_stats_param("고령화지수"), region="부산")
    assert spec["codes"] == {"itmId": "T4", "objL1": "01", "objL2": "21"}
    spec, _ = param_spec(get_quick_stats_param("고령화지수"), all_regions=True)
    assert spec["codes"]["objL2"] == "ALL" and spec["codes"]["objL1"] == "01"


def test_param_spec_unknown_region():
    spec, name = param_spec(get_quick_stats_param("인구"), region="아틀란티스")
    assert spec is None and name == "아틀란티스"


async def test_district_spec_object_level_2():
    route = {"orgId": "101", "tblId": "T", "itmId": "T4", "prdSe": "Y", "districtObjLevel": 2, "extraObjL1": "01"}
    spec = await keyword_mod.district_spec(route, "강남구", all_regions=True)
    assert spec["codes"] == {"objL1": "01", "objL2": "ALL", "itmId": "T4"}


def _cmp_rows(*rows):
    return {
        "success": True,
        "rows": [
            {"key": k, "level": lv, "values": {"value": {"value": v, "unit": "명", "period": "2025"}}, "ranks": {"value": r}}
            for k, lv, v, r in rows
        ],
    }


@pytest.fixture
def fake_compare(monkeypatch):
    seen: list = []

    async def fake(series, *a, **kw):
        seen.append(series[0])
        if series[0].get("level") == "sigungu":
            return _cmp_rows(("서울 중구", "sigungu", 120, 1), ("부산 중구", "sigungu", 40, 2), ("서울 강남구", "sigungu", 30, 3))
        # 전국 행은 compare_values에서 total로 빠진다 → rows에 없음.
        return _cmp_rows(("경기", "sido", 300, 1), ("서울", "sido", 200, 2), ("부산", "sido", 100, 3))

    monkeypatch.setattr(more_tools, "compare_values", fake)
    return seen


async def test_quick_rank_sido_excludes_national(fake_compare):
    out = await more_tools.quick_rank("인구", "서울")
    assert out["success"] and out["rank"] == 2 and out["total"] == 3
    assert out["average"] == pytest.approx(200)
    spec = fake_compare[0]
    assert spec["level"] == "sido" and spec["codes"]["objL1"] == "ALL"


async def test_quick_rank_ambiguous_district(fake_compare):
    out = await more_tools.quick_rank("인구", "중구")
    assert not out["success"]
    assert "서울 중구" in out["answer"] and "부산 중구" in out["answer"]
    out = await more_tools.quick_rank("인구", "부산 중구")
    assert out["success"] and out["region"] == "부산 중구" and out["rank"] == 2


async def test_compare_regions_adds_ranks(monkeypatch):
    values = {("서울", "인구"): "9,300,000", ("부산", "인구"): "3,200,000", ("세종", "인구"): None}

    async def fake_quick_stats(query, region):
        v = values[(region, query)]
        return {"success": v is not None, "value": v, "unit": "명", "period": "2025년", "answer": ""}

    monkeypatch.setattr(more_tools, "quick_stats", fake_quick_stats)
    out = await more_tools.compare_regions(["서울", "부산", "세종"], ["인구"])
    assert [(r["region"], r["rank"]) for r in out["ranks"]["인구"]] == [("서울", 1), ("부산", 2)]
    assert out["matrix"][0]["numericValue"] == 9_300_000


async def test_quick_trend_district_region_uses_route(monkeypatch):
    calls = []

    async def fake_district_spec(route, district, *, province=None, all_regions=False):
        calls.append(district)
        return {"orgId": route["orgId"], "tableId": route["tblId"], "codes": {"objL1": "11680", "itmId": route["itmId"]}, "periodType": "Y"}

    async def fake_fetch(spec, **kw):
        pts = [{"period": str(y), "value": 100.0 + y - 2020, "raw": str(100 + y - 2020)} for y in range(2020, 2026)]
        return {"series": [{"points": pts}], "resolved": {}}

    monkeypatch.setattr(more_tools, "district_spec", fake_district_spec)
    monkeypatch.setattr(more_tools, "fetch_spec", fake_fetch)
    out = await more_tools.quick_trend("인구", region="강남구")
    assert out["success"] and out["region"] == "강남구" and calls == ["강남구"]
    assert out["dataPoints"][-1]["changeRate"].startswith("+")
    assert out["cagr"] > 0


def test_series_tools_exported():
    assert callable(series_tools.analyze_trend) and callable(series_tools.compare_values)


def test_province_alias_is_not_a_district():
    from kosis_mcp.tools.quick_stats import extract_district_name

    assert extract_district_name("서울시") is None
    assert extract_district_name("광주시") == "광주시"  # 경기 광주시는 실제 기초자치단체


@pytest.fixture
def fake_series(monkeypatch):
    seen: list[dict] = []

    async def fake_fetch(spec, **kw):
        seen.append({"spec": spec, **kw})
        sub = "" if spec.get("periodType", "Y") == "Y" else "01"
        pts = [{"period": f"{y}{sub}", "value": 100.0 + y - 2020, "raw": str(100 + y - 2020)} for y in range(2020, 2026)]
        return {"series": [{"points": pts, "unit": "십억원"}], "resolved": {}}

    async def no_live(*a, **kw):
        return None

    monkeypatch.setattr(more_tools, "fetch_spec", fake_fetch)
    monkeypatch.setattr(more_tools, "resolve_region_code", no_live)
    return seen


async def test_quick_trend_unsupported_region_is_flagged_fallback(fake_series):
    out = await more_tools.quick_trend("GDP", region="부산")
    assert out["success"] and out["isFallback"] and out["fallbackRegion"] == "전국"
    assert out["unit"] == "십억원"


async def test_quick_trend_year_count_scales_with_period(fake_series):
    await more_tools.quick_trend("아파트가격", yearCount=3)
    assert fake_series[-1]["recent"] == 36


async def test_quick_rank_percentile(fake_compare):
    out = await more_tools.quick_rank("인구", "경기")
    assert out["rank"] == 1 and out["percentile"] == 100.0


async def test_compare_regions_skips_fallback_cells(monkeypatch):
    async def fake_quick_stats(query, region):
        if region == "영종구":
            return {"success": True, "value": "51,000,000", "period": "2025년", "isFallback": True, "fallbackRegion": "전국"}
        return {"success": True, "value": "100", "period": "2025년"}

    monkeypatch.setattr(more_tools, "quick_stats", fake_quick_stats)
    out = await more_tools.compare_regions(["서울", "영종구"], ["인구"])
    assert [r["region"] for r in out["ranks"]["인구"]] == ["서울"]
    assert out["matrix"][1]["isFallback"]
    assert any("영종구" in w for w in out["warnings"])


async def test_quick_stats_unknown_region_flags_fallback_and_keys_period(monkeypatch):
    from kosis_mcp.tools import quick_stats as qs

    keys: list[dict] = []

    class FakeCache:
        async def get_statistics_data(self, params, fetcher):
            keys.append(params)
            return [{"PRD_DE": "2025", "DT": "51117378"}]

    async def no_live(*a, **kw):
        return None

    monkeypatch.setattr(qs, "get_cache_manager", lambda: FakeCache())
    monkeypatch.setattr(qs, "get_kosis_client", lambda: None)
    monkeypatch.setattr(qs, "resolve_region_code", no_live)
    out = await qs.quick_stats("인구", region="아틀란티스")
    assert out["success"] and out["isFallback"] and out["fallbackRegion"] == "전국"
    await qs.quick_stats("실업률", year=2024, period="M", month=3)
    await qs.quick_stats("실업률", year=2024, period="M", month=5)
    assert keys[-2]["startPrdDe"] != keys[-1]["startPrdDe"]
