"""L2 tests for find_tables orchestration (KOSIS API mocked)."""

import pytest

from kosis_mcp.population_search import find as find_mod
from kosis_mcp.population_search.categories import category_counts, category_of

POP_ROW = {
    "orgId": "101",
    "tableId": "DT_POP",
    "tableName": "행정구역별 인구",
    "statName": "주민등록인구현황",
    "statId": "1962001",
    "path": "인구 > 주민등록인구현황 > 행정구역별",
    "startPeriod": "1992",
    "endPeriod": "2026",
}
JOB_ROW = {
    "orgId": "101",
    "tableId": "DT_JOB",
    "tableName": "성별 경제활동인구",
    "statName": "경제활동인구조사",
    "path": "노동 > 경제활동인구조사 > 총괄",
}


@pytest.fixture
def calls(monkeypatch):
    log: list[dict] = []

    async def fake_search(query, *, axes=None, org_id=None, sort="RANK", limit=10):
        log.append({"query": query, "org_id": org_id, "axes": axes, "limit": limit})
        rows = [JOB_ROW, POP_ROW] if "고용" in query else [POP_ROW, JOB_ROW]
        return rows, [query], {}

    async def fake_verify(query, candidates):
        verified = [
            {**c, "score": 1.0 - i * 0.3, "passed": True} for i, c in enumerate(candidates)
        ]
        return {"success": True, "query": query, "verified": verified}

    monkeypatch.setattr(find_mod, "api_search_candidates", fake_search)
    monkeypatch.setattr(find_mod, "batch_verify_table_candidates", fake_verify)
    return log


def test_category_of_reads_any_path_level():
    assert category_of(POP_ROW) == "인구"
    assert category_of({"path": "주제별 > 인구"}) == "인구"
    assert category_of({"path": "주제별"}) is None
    assert category_counts([POP_ROW, POP_ROW, JOB_ROW]) == {"인구": 2, "노동": 1}


async def test_search_uses_general_path_and_explicit_axes_only(calls):
    out = await find_mod.find_tables("서울 65세 이상 인구")
    assert calls[-1]["org_id"] is None
    assert calls[-1]["axes"] == []
    assert {a["category"] for a in out["debug"]["axes"]} >= {"region", "age"}
    assert out["action"] == "single_table"


async def test_candidates_exclude_decided_tables(calls):
    out = await find_mod.find_tables("서울 인구 통계표 찾아줘")
    table_ids = {t["tableId"] for t in out["tables"]}
    cand_ids = [c["tableId"] for c in out["candidates"]]
    assert table_ids.isdisjoint(cand_ids)
    assert table_ids | set(cand_ids) == {"DT_POP", "DT_JOB"}
    assert all("confidence" in c for c in out["candidates"])


async def test_category_filters_candidates(calls):
    out = await find_mod.find_tables("고용 현황", category="노동")
    assert [t["tableId"] for t in out["tables"]] == ["DT_JOB"]
    assert calls[-1]["limit"] == 30


async def test_tables_carry_reference_fields(calls):
    out = await find_mod.find_tables("서울 인구", category="인구")
    top = out["tables"][0]
    assert top["statId"] == "1962001"
    assert top["category"] == "인구"
    assert top["periodRange"] == {"start": "1992", "end": "2026"}


async def test_get_value_intent_adds_next_hint(calls):
    out = await find_mod.find_tables("서울 인구 몇 명이야")
    assert out["debug"]["intent"] == "get_value"
    assert "get_statistics_data" in out["next"]
    assert out["tables"]


async def test_decompose_merges_sub_queries(calls):
    out = await find_mod.find_tables("서울 인구와 고용 현황", decompose=True)
    assert out["action"] == "multi_table"
    assert [s["query"] for s in out["debug"]["subQueries"]] == ["서울 인구", "고용 현황"]
    assert {t["tableId"] for t in out["tables"]} == {"DT_POP", "DT_JOB"}


async def test_empty_search_error_becomes_no_rows():
    from kosis_mcp.client import KosisApiError
    from kosis_mcp.tools.more_tools import _merge_search_results

    class EmptyCache:
        def _generate_key(self, prefix, params):
            return prefix

        async def _get(self, key):
            return None

        async def get_search_results(self, params, fetcher):
            raise KosisApiError("30", "데이터가 존재하지 않습니다.")

    rows, per_term = await _merge_search_results(
        EmptyCache(), None, ["없는 표"], None, "RANK", 10, {}
    )
    assert rows == []
    assert per_term[0]["count"] == 0


async def test_categories_counted_before_filter_and_next_needs_tables(calls, monkeypatch):
    out = await find_mod.find_tables("고용 현황", category="노동")
    assert out["debug"]["categories"] == {"노동": 1, "인구": 1}

    async def empty(query, *, axes=None, org_id=None, sort="RANK", limit=10):
        return [], [query], {}

    monkeypatch.setattr(find_mod, "api_search_candidates", empty)
    out = await find_mod.find_tables("서울 인구 몇 명이야")
    assert out["action"] == "no_exact_table" and "next" not in out
