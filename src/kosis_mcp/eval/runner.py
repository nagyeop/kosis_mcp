"""Langfuse experiment runner for L3 tool-direct eval."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Literal

from langfuse import Langfuse, observe

from kosis_mcp.client import KosisApiError
from kosis_mcp.eval.evaluators import EVALUATOR_VERSION, item_evaluator
from kosis_mcp.eval.outcome import MODE_TOOL_ALIASES, normalize_outcome
from kosis_mcp.server import (
    _should_export_span,
    tool_browse_statistics,
    tool_find_tables,
    tool_quick_stats,
)

EvalTool = Literal["find_tables", "quick_stats", "browse_statistics"]

TOOL_REGISTRY: dict[str, Any] = {
    "find_tables": tool_find_tables,
    "quick_stats": tool_quick_stats,
    "browse_statistics": tool_browse_statistics,
}


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    tool: EvalTool
    cache: Literal["bypass", "use"] = "bypass"
    limit: int = 10
    concurrency: int = 1

    @classmethod
    def from_mode(cls, run_id: str, mode: str, **kwargs: Any) -> RunConfig:
        tool = MODE_TOOL_ALIASES.get(mode)
        if tool is None:
            raise ValueError(f"unsupported mode alias: {mode}")
        return cls(run_id=run_id, tool=tool, **kwargs)  # type: ignore[arg-type]


async def invoke_tool(
    run_config: RunConfig, query: str, category: str | None = None
) -> dict[str, Any]:
    fn = TOOL_REGISTRY.get(run_config.tool)
    if fn is None:
        raise ValueError(f"unsupported tool: {run_config.tool}")

    if run_config.tool == "find_tables":
        return await fn(query, category=category)
    if run_config.tool == "browse_statistics":
        # browse는 탐색 tool이라 query를 쓰지 않는다 — 항목의 검색 범위(분야) 단위로 평가한다.
        return await fn(category=category, limit=run_config.limit)
    return await fn(query)


# KOSIS OpenAPI allows 200 calls/min per key; wait out the window and retry.
_RATE_LIMIT_MARK = "호출가능건수"
_RATE_LIMIT_WAIT_S = 61
_RATE_LIMIT_RETRIES = 3


async def _invoke_with_rate_limit_retry(
    run_config: RunConfig, query: str, category: str | None
) -> dict[str, Any]:
    for attempt in range(_RATE_LIMIT_RETRIES + 1):
        try:
            out = await invoke_tool(run_config, query, category)
        except KosisApiError as e:
            if _RATE_LIMIT_MARK not in str(e) or attempt == _RATE_LIMIT_RETRIES:
                raise
            await asyncio.sleep(_RATE_LIMIT_WAIT_S)
            continue
        # quick_stats·verify 경로는 오류를 응답 dict 안에 담는다 → 한도 메시지가 있으면 다시 시도.
        if _RATE_LIMIT_MARK in str(out) and attempt < _RATE_LIMIT_RETRIES:
            await asyncio.sleep(_RATE_LIMIT_WAIT_S)
            continue
        return out
    raise AssertionError("unreachable")


def make_task(run_config: RunConfig):
    @observe(name="population_search_eval", as_type="span")
    async def task(*, item: Any, **kwargs: Any) -> dict[str, Any]:
        inp = item.input or {}
        raw = await _invoke_with_rate_limit_retry(
            run_config, inp.get("query", ""), inp.get("category")
        )
        out = normalize_outcome(raw, tool=run_config.tool)
        return out

    return task


def run_experiment(run_config: RunConfig, dataset_name: str) -> Any:
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        raise RuntimeError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required")

    if run_config.cache == "bypass":
        os.environ["EVAL_CACHE_BYPASS"] = "1"
    else:
        os.environ.pop("EVAL_CACHE_BYPASS", None)

    langfuse = Langfuse(should_export_span=_should_export_span)
    try:
        dataset = langfuse.get_dataset(dataset_name)
        return dataset.run_experiment(
            name=run_config.run_id,
            description=(
                f"baseline_type=mcp tool={run_config.tool} cache={run_config.cache} "
                + (f"limit={run_config.limit} " if run_config.tool == "browse_statistics" else "")
                + f"concurrency={run_config.concurrency} evaluator={EVALUATOR_VERSION}"
            ),
            task=make_task(run_config),
            evaluators=[item_evaluator],
            max_concurrency=run_config.concurrency,
            metadata={
                "baseline_type": "mcp",
                "run_id": run_config.run_id,
                "tool": run_config.tool,
                "cache": run_config.cache,
                **({"limit": str(run_config.limit)} if run_config.tool == "browse_statistics" else {}),
                "evaluator_version": EVALUATOR_VERSION,
            },
        )
    finally:
        langfuse.shutdown()
