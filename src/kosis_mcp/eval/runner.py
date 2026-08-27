"""Langfuse experiment runner for L3 tool-direct eval."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from langfuse import Langfuse, observe

from kosis_mcp.eval.evaluators import item_evaluator
from kosis_mcp.eval.outcome import normalize_outcome
from kosis_mcp.server import (
    _should_export_span,
    tool_get_statistics_list,
    tool_quick_stats,
    tool_search_statistics,
)

EvalMode = Literal["direct_search", "direct_quick", "direct_list"]


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    mode: EvalMode
    cache: Literal["bypass", "use"] = "bypass"
    limit: int = 10


async def invoke_tool(run_config: RunConfig, query: str) -> dict[str, Any]:
    if run_config.mode == "direct_search":
        return await tool_search_statistics(query, limit=run_config.limit)
    if run_config.mode == "direct_quick":
        return await tool_quick_stats(query)
    if run_config.mode == "direct_list":
        return await tool_get_statistics_list(
            recommendedTopic="population",
            limit=run_config.limit,
        )
    raise ValueError(f"unsupported mode: {run_config.mode}")


def make_task(run_config: RunConfig):
    # @observe so nested tool/openapi spans attach; dataset.run_experiment links the run.
    @observe(name="population_search_eval", as_type="span")
    async def task(*, item: Any, **kwargs: Any) -> dict[str, Any]:
        inp = item.input or {}
        raw = await invoke_tool(run_config, inp.get("query", ""))
        return normalize_outcome(run_config.mode, raw)

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
                f"baseline_type=mcp mode={run_config.mode} "
                f"cache={run_config.cache} limit={run_config.limit}"
            ),
            task=make_task(run_config),
            evaluators=[item_evaluator],
            max_concurrency=3,
            metadata={
                "baseline_type": "mcp",
                "run_id": run_config.run_id,
                "mode": run_config.mode,
                "cache": run_config.cache,
                "limit": str(run_config.limit),
            },
        )
    finally:
        langfuse.shutdown()
