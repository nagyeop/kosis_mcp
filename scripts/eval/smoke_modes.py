#!/usr/bin/env python3
"""Smoke: call each eval tool once on gold Q001 and print outcome shape."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from kosis_mcp.eval.outcome import normalize_outcome
from kosis_mcp.eval.runner import RunConfig, invoke_tool

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "tests" / "testset" / "gold_queries.json"
TOOLS = [
    "find_tables",
    "quick_stats",
    "browse_statistics",
]


async def main() -> None:
    load_dotenv()
    os.environ["EVAL_CACHE_BYPASS"] = "1"

    row = next(
        (
            candidate
            for candidate in json.loads(GOLD.read_text(encoding="utf-8"))
            if candidate.get("query_id") == "Q001"
        ),
        None,
    )
    if row is None:
        raise SystemExit("Q001 not found in gold_queries.json")

    query = row["query"]
    print(f"query_id=Q001 query={query!r}\n")

    for tool in TOOLS:
        cfg = RunConfig(run_id=f"smoke-{tool}", tool=tool, cache="bypass", limit=10)  # type: ignore[arg-type]
        raw = await invoke_tool(cfg, query, row.get("scope_category"))
        out = normalize_outcome(raw, tool=tool)
        print(f"=== {tool} (family={out['response_family']}) ===")
        print(json.dumps(out, ensure_ascii=False, indent=2))
        print()


if __name__ == "__main__":
    asyncio.run(main())
