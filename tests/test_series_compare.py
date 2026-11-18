"""L2 tests for series resolve/fetch grouping and analyze_trend / compare_values (KOSIS mocked)."""

import pytest

from kosis_mcp.series import fetch as fetch_mod
from kosis_mcp.series import resolve as resolve_mod
from kosis_mcp.series.fetch import group_rows
from kosis_mcp.tools import series_tools


def _region(code, name, up=None, sn="1", obj="A", obj_nm="행정구역(시군구)별"):
    return {"OBJ_ID": obj, "OBJ_NM": obj_nm, "OBJ_ID_SN": sn, "ITM_ID": code, "ITM_NM": name, "UP_ITM_ID": up}


def _item(code, name, unit):
    return {"OBJ_ID": "ITEM", "OBJ_NM": "항목", "OBJ_ID_SN": None, "ITM_ID": code, "ITM_NM": name, "UNIT_NM": unit}


SIGUNGU_REGIONS = [
    _region("00", "전국"),
    _region("11", "서울특별시"),
    _region("11110", "종로구", "11"),
    _region("11140", "중구", "11"),
    _region("26", "부산광역시"),
    _region("26110", "중구", "26"),
]
META = {
    "DT_POP": [_item("T20", "총인구수", "명"), _item("T21", "남자인구수", "명"), *SIGUNGU_REGIONS],
    "DT_HH": [_item("T1", "세대수", "세대"), *SIGUNGU_REGIONS],
    # 인구총조사: 시도 코드 체계가 다르고(부산 21) 단위가 천명.
    "DT_CEN": [
        _item("T100", "총인구", "천명"),
        _region("00", "전국", obj_nm="행정구역별(읍면동)"),
        _region("03", "동부", obj_nm="행정구역별(읍면동)"),
        _region("11", "서울특별시", obj_nm="행정구역별(읍면동)"),
        _region("21", "부산광역시", obj_nm="행정구역별(읍면동)"),
    ],
}
PERIODS = {"DT_POP": ["M", "Y"], "DT_HH": ["M"], "DT_CEN": ["Y"]}
UNITS = {"T20": "명", "T21": "명", "T1": "세대", "T100": "천명"}


def _values(tbl, item, code, period):
    base = {"00": 1000, "11": 400, "11110": 50, "11140": 40, "26": 300, "26110": 30, "03": 800, "21": 300}[code]
    k = {"DT_POP": 1, "DT_HH": 0.5, "DT_CEN": 0.001}[tbl]
    bump = int(period[:4]) - 2020 + (int(period[4:]) if len(period) > 4 else 0) / 100
    v = base * k * (1 + bump / 100)
    if item == "T21":
        v /= 2
    return v


PERIOD_DATA = {
    "M": [f"{y}{m:02d}" for y in (2024, 2025) for m in range(1, 13)] + [f"2026{m:02d}" for m in range(1, 10)],
    "Y": ["2021", "2022", "2023", "2024", "2025"],
}


@pytest.fixture
def kosis(monkeypatch):
    calls: list[dict] = []

    async def fake_meta(org_id, tbl_id):
        return META[tbl_id]

    async def fake_periods(org_id, tbl_id):
        return [{"periodType": p, "start": "", "end": ""} for p in PERIODS[tbl_id]]

    async def fake_rows(params):
        calls.append(params)
        tbl = params["tblId"]
        regions = [m for m in META[tbl] if m["OBJ_ID"] != "ITEM"]
        items = [m for m in META[tbl] if m["OBJ_ID"] == "ITEM"]
        objl = params.get("objL1", "ALL")
        codes = [r["ITM_ID"] for r in regions] if objl == "ALL" else [c for c in objl.split("+") if c]
        itm = params.get("itmId", "ALL")
        item_ids = [i["ITM_ID"] for i in items] if itm == "ALL" else itm.split("+")
        periods = PERIOD_DATA[params["prdSe"]]
        if "newEstPrdCnt" in params:
            periods = periods[-int(params["newEstPrdCnt"]):]
        else:
            periods = [p for p in periods if params["startPrdDe"] <= p <= params["endPrdDe"]]
        names = {r["ITM_ID"]: r["ITM_NM"] for r in regions}
        item_names = {i["ITM_ID"]: i["ITM_NM"] for i in items}
        return [
            {
                "TBL_NM": tbl,
                "ITM_ID": i,
                "ITM_NM": item_names[i],
                "C1": c,
                "C1_NM": names[c],
                "C1_OBJ_NM": regions[0]["OBJ_NM"],
                "PRD_DE": p,
                "DT": str(round(_values(tbl, i, c, p), 3)),
                "UNIT_NM": UNITS[i],
            }
            for i in item_ids
            for c in codes
            for p in periods
        ]

    monkeypatch.setattr(resolve_mod, "fetch_table_meta", fake_meta)
    monkeypatch.setattr(resolve_mod, "table_period_types", fake_periods)
    monkeypatch.setattr(fetch_mod, "fetch_rows", fake_rows)
    return calls


async def test_resolve_regions_with_province_prefix(kosis):
    out = await resolve_mod.resolve_spec({"orgId": "101", "tableId": "DT_POP", "regions": ["서울", "부산 중구"]})
    assert out["params"]["objL1"] == "11+26110"
    assert out["periodType"] == "M"
    assert {"objNm": "항목", "itmNm": "총인구수", "itmId": "T20"} in out["appliedDefaults"]


async def test_resolve_ambiguous_region_returns_candidates(kosis):
    out = await resolve_mod.resolve_spec({"orgId": "101", "tableId": "DT_POP", "regions": ["중구"]})
    assert out["unmatched"] == {"regions": ["중구"]}
    assert out["candidates"]["행정구역(시군구)별"] == ["서울 중구", "부산 중구"]


def test_group_rows_splits_series_per_item_and_region():
    rows = [
        {"ITM_ID": i, "ITM_NM": i, "C1": c, "C1_NM": c, "PRD_DE": p, "DT": "1", "UNIT_NM": "명"}
        for i in ("T20", "T21")
        for c in ("11", "26")
        for p in ("2024", "2025")
    ]
    series = group_rows(rows, region_objl="objL1")
    assert len(series) == 4
    assert all(len(s["points"]) == 2 for s in series)


async def test_compare_single_table_sido_rank_share(kosis):
    out = await series_tools.compare_values(
        [{"orgId": "101", "tableId": "DT_POP", "regions": "ALL", "level": "sido", "label": "인구"}]
    )
    assert out["success"]
    assert [r["key"] for r in out["rows"]] == ["서울", "부산"]
    assert [r["ranks"]["인구"] for r in out["rows"]] == [1, 2]
    seoul = out["rows"][0]["values"]["인구"]
    assert seoul["period"] == "202609"
    assert seoul["share"] == pytest.approx(40.0)
    assert out["columns"][0]["total"]["key"] == "전국"


async def test_compare_mixed_levels_ranked_separately(kosis):
    out = await series_tools.compare_values([{"orgId": "101", "tableId": "DT_POP", "regions": "ALL"}])
    ranks = {(r["level"], r["key"]): r["ranks"]["s1"] for r in out["rows"]}
    assert ranks[("sido", "서울")] == 1
    assert ranks[("sigungu", "서울 종로구")] == 1
    assert ranks[("sigungu", "부산 중구")] == 3
    assert any("수준" in w for w in out["warnings"])


async def test_compare_same_concept_different_tables(kosis):
    out = await series_tools.compare_values(
        [
            {"orgId": "101", "tableId": "DT_POP", "regions": ["서울", "부산"], "label": "주민등록"},
            {"orgId": "101", "tableId": "DT_CEN", "regions": ["서울", "부산"], "label": "총조사"},
        ]
    )
    busan = next(r for r in out["rows"] if r["key"] == "부산")
    # 코드가 달라도(26 vs 21) 이름으로 조인, 연말값과 연값을 2025년으로 정렬.
    assert busan["values"]["주민등록"]["period"] == "202512"
    assert busan["values"]["총조사"]["period"] == "2025"
    # 천명 → 명 정규화 후 차이 계산.
    assert busan["values"]["총조사"]["originalUnit"] == "천명"
    assert busan["diffFrom"]["base"] == "주민등록"
    assert abs(busan["diffFrom"]["총조사"]["rate"]) < 1
    assert out["notes"][0]["type"] == "definition"


async def test_compare_derive_across_tables(kosis):
    out = await series_tools.compare_values(
        [
            {"orgId": "101", "tableId": "DT_POP", "regions": "ALL", "level": "sido", "label": "인구"},
            {"orgId": "101", "tableId": "DT_HH", "regions": "ALL", "level": "sido", "label": "세대"},
        ],
        derive=[{"name": "세대당인구", "expr": "인구 / 세대"}],
    )
    assert out["derived"][0]["unit"] == "명/세대"
    assert out["rankedBy"] == "세대당인구"
    assert out["rows"][0]["derived"]["세대당인구"] == pytest.approx(2.0)
    # derive를 줬으면 단위가 다른 열의 차이 미계산 경고는 내지 않는다.
    assert not any("단위" in w for w in out.get("warnings", []))


async def test_compare_unknown_derive_name(kosis):
    out = await series_tools.compare_values(
        [{"orgId": "101", "tableId": "DT_POP", "regions": ["서울"]}],
        derive=[{"name": "x", "expr": "s9 / s1"}],
    )
    assert not out["success"] and "s9" in out["error"]


async def test_compare_unmatched_returns_failures(kosis):
    out = await series_tools.compare_values([{"orgId": "101", "tableId": "DT_POP", "item": "외국인"}])
    assert not out["success"]
    assert out["failures"][0]["unmatched"] == {"item": ["외국인"]}
    assert "총인구수" in out["failures"][0]["candidates"]["항목"]


async def test_compare_cache_params_are_complete(kosis):
    await series_tools.compare_values([{"orgId": "101", "tableId": "DT_POP", "regions": ["서울"], "item": "남자"}])
    p = kosis[-1]
    assert (p["objL1"], p["itmId"], p["prdSe"]) == ("11", "T21", "M")


async def test_analyze_trend_multi_series_comparison(kosis):
    out = await series_tools.analyze_trend(
        [
            {"orgId": "101", "tableId": "DT_POP", "regions": ["서울", "부산"], "periodType": "Y"},
            {"orgId": "101", "tableId": "DT_CEN", "regions": ["서울"], "label": "총조사"},
        ],
        recentCount=5,
    )
    assert out["success"]
    assert [s["name"] for s in out["series"]] == ["s1 · 서울", "s1 · 부산", "총조사"]
    assert out["series"][0]["analysis"]["cagr"] is not None
    assert out["comparison"]["commonRange"] == {"start": "2021", "end": "2025"}
    assert kosis[0]["newEstPrdCnt"] == 5


async def test_analyze_trend_defaults_to_yearly(kosis):
    out = await series_tools.analyze_trend([{"orgId": "101", "tableId": "DT_POP", "regions": ["서울"]}])
    assert out["series"][0]["periodType"] == "Y"
    assert {"objNm": "주기", "itmNm": "Y", "itmId": "Y"} in out["tables"][0]["appliedDefaults"]


def test_region_index_structural_sido():
    idx = resolve_mod.RegionIndex(
        [
            _region("00", "전국"),
            _region("12", "전남광주통합특별시"),
            _region("12110", "목포시", "12"),
            _region("03", "동부"),
        ]
    )
    assert idx.level("12") == "sido"
    assert idx.level("12110") == "sigungu"
    assert idx.join_key("12110") == "전남광주 목포시"
    assert idx.level("03") == "other"


async def test_compare_single_region_items_become_rows(kosis):
    out = await series_tools.compare_values(
        [{"orgId": "101", "tableId": "DT_POP", "regions": ["서울"], "item": ["총인구수", "남자인구수"]}]
    )
    assert [r["key"] for r in out["rows"]] == ["총인구수", "남자인구수"]
    assert out["columns"][0]["region"] == "서울"
    assert [r["ranks"]["s1"] for r in out["rows"]] == [1, 2]


async def test_compare_excludes_rows_missing_latest_period(kosis, monkeypatch):
    original = fetch_mod.fetch_rows

    async def drop_busan_latest(params):
        rows = await original(params)
        return [r for r in rows if not (r["C1"] == "26" and r["PRD_DE"] == "202609")]

    monkeypatch.setattr(fetch_mod, "fetch_rows", drop_busan_latest)
    out = await series_tools.compare_values(
        [{"orgId": "101", "tableId": "DT_POP", "regions": "ALL", "level": "sido"}]
    )
    assert [r["key"] for r in out["rows"]] == ["서울"]
    assert out["columns"][0]["period"] == "202609"
    assert any("부산" in w and "제외" in w for w in out["warnings"])


def test_region_index_general_gu_and_subdistrict_keys():
    idx = resolve_mod.RegionIndex(
        [
            _region("31", "경기도"),
            _region("31010", "수원시", "31"),
            _region("31011", "장안구", "31"),  # KOSIS 메타: 일반구의 상위가 도
            _region("11", "서울특별시"),
            _region("11680", "강남구", "11"),
            _region("11620", "관악구", "11"),
            _region("11680510", "신사동", "11680"),
            _region("11620685", "신사동", "11620"),
            _region("28", "인천광역시"),
            _region("28170", "남구", "28"),
            _region("28177", "미추홀구", "28"),  # 남구의 개칭 후 코드 — 하위 지역 아님
        ]
    )
    assert idx.level("28177") == "sigungu"
    assert idx.level("31010") == "sigungu"
    assert idx.level("31011") == "subdistrict"
    assert idx.join_key("31011") == "경기 수원시 장안구"
    assert idx.join_key("11680510") != idx.join_key("11620685")
    assert idx.match("서울 강남구 신사동") == (["11680510"], [])
    codes, ambiguous = idx.match("신사동")
    assert not codes and set(ambiguous) == {"서울 강남구 신사동", "서울 관악구 신사동"}


async def test_regions_string_is_wrapped(kosis):
    out = await resolve_mod.resolve_spec({"orgId": "101", "tableId": "DT_POP", "regions": "서울"})
    assert out["params"]["objL1"] == "11"


async def test_ambiguous_partial_item_is_unmatched(kosis):
    out = await resolve_mod.resolve_spec({"orgId": "101", "tableId": "DT_POP", "item": "인구"})
    assert out["unmatched"] == {"item": ["인구"]}
    assert set(out["candidates"]["항목"]) == {"총인구수", "남자인구수"}


async def test_failure_kinds_are_classified(kosis, monkeypatch):
    from kosis_mcp.client import KosisApiError

    async def too_large(params):
        raise KosisApiError("31", " 40,000셀을 초과한 결과값은 요청하실 수 없습니다.")

    monkeypatch.setattr(fetch_mod, "fetch_rows", too_large)
    out = await series_tools.compare_values([{"orgId": "101", "tableId": "DT_POP", "regions": "ALL"}])
    assert not out["success"] and out["failures"][0]["error"] == "too_large"

    async def no_meta(org_id, tbl_id):
        raise KosisApiError("30", "데이터가 존재하지 않습니다.")

    monkeypatch.setattr(resolve_mod, "fetch_table_meta", no_meta)
    out = await series_tools.compare_values([{"orgId": "101", "tableId": "DT_NOPE"}])
    assert out["failures"][0]["error"] == "no_table"


async def test_out_of_range_period_is_failure(kosis):
    out = await series_tools.compare_values([{"orgId": "101", "tableId": "DT_POP", "regions": ["서울"]}], period="1980")
    assert not out["success"]
    assert out["error"] == "조건에 해당하는 데이터가 없습니다."


async def test_bad_period_is_failure(kosis):
    out = await series_tools.compare_values([{"orgId": "101", "tableId": "DT_POP", "regions": ["서울"]}], period="작년")
    assert out["failures"][0]["error"] == "bad_period"


async def test_top_must_be_positive(kosis):
    out = await series_tools.compare_values([{"orgId": "101", "tableId": "DT_POP"}], top=0)
    assert not out["success"]


async def test_derive_does_not_mutate_input(kosis):
    derive = [{"name": "r", "expr": "인구 / 세대"}]
    await series_tools.compare_values(
        [
            {"orgId": "101", "tableId": "DT_POP", "regions": "ALL", "level": "sido", "label": "인구"},
            {"orgId": "101", "tableId": "DT_HH", "regions": "ALL", "level": "sido", "label": "세대"},
        ],
        derive=derive,
    )
    assert derive == [{"name": "r", "expr": "인구 / 세대"}]


def test_facet_total_requires_all_varying_dims_total():
    def ser(sex, age):
        return {
            "item": {"id": "T", "name": "인구"},
            "region": None,
            "dims": [
                {"objNm": "성별", "code": sex, "name": {"0": "계", "1": "남자"}[sex]},
                {"objNm": "연령", "code": age, "name": {"0": "계", "20": "20대"}[age]},
            ],
        }

    sers = [ser("0", "0"), ser("0", "20"), ser("1", "0"), ser("1", "20")]
    facets = series_tools._varying_facets(sers)
    assert [facets[id(s)][1] for s in sers] == [True, False, False, False]


async def test_trend_per_spec_cap_and_metric(kosis, monkeypatch):
    monkeypatch.setattr(series_tools, "MAX_TREND_SERIES", 4)
    out = await series_tools.analyze_trend(
        [
            {"orgId": "101", "tableId": "DT_POP", "regions": "ALL", "periodType": "Y"},
            {"orgId": "101", "tableId": "DT_CEN", "regions": ["서울"], "label": "총조사"},
        ],
        recentCount=5,
    )
    names = [s["name"] for s in out["series"]]
    assert "총조사" in names and len(names) == 3
    assert any("제외" in w for w in out["warnings"])
    assert out["comparison"]["rankedBy"] == "cagr"
