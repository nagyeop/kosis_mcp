"""L2 tests for eval runner dispatch."""

from kosis_mcp.eval import runner


async def test_find_tables_receives_dataset_scope(monkeypatch):
    seen = {}

    async def fake_find(query, category=None):
        seen.update(query=query, category=category)
        return {"action": "no_exact_table", "tables": []}

    monkeypatch.setitem(runner.TOOL_REGISTRY, "find_tables", fake_find)
    cfg = runner.RunConfig(run_id="t", tool="find_tables")
    await runner.invoke_tool(cfg, "범죄율", "인구")
    assert seen == {"query": "범죄율", "category": "인구"}


async def test_browse_receives_dataset_scope(monkeypatch):
    seen = {}

    async def fake_browse(category=None, limit=50):
        seen.update(category=category, limit=limit)
        return {"items": []}

    monkeypatch.setitem(runner.TOOL_REGISTRY, "browse_statistics", fake_browse)
    cfg = runner.RunConfig(run_id="t", tool="browse_statistics", limit=7)
    await runner.invoke_tool(cfg, "아무 질의", "보건")
    assert seen == {"category": "보건", "limit": 7}


async def test_retry_when_rate_limit_is_inside_response(monkeypatch):
    calls = []

    async def fake_quick(query):
        calls.append(query)
        if len(calls) == 1:
            return {"success": False, "answer": "조회 중 오류: 1분간 호출가능건수(200건) 초과"}
        return {"success": True, "value": "1"}

    async def no_sleep(_s):
        return None

    monkeypatch.setitem(runner.TOOL_REGISTRY, "quick_stats", fake_quick)
    monkeypatch.setattr(runner.asyncio, "sleep", no_sleep)
    cfg = runner.RunConfig(run_id="t", tool="quick_stats")
    out = await runner._invoke_with_rate_limit_retry(cfg, "인구", None)
    assert out["success"] and len(calls) == 2
