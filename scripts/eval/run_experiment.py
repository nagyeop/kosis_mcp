#!/usr/bin/env python3
"""Run L3 population search eval experiment on a Langfuse dataset."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from kosis_mcp.eval.runner import RunConfig, run_experiment


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run population search L3 eval")
    parser.add_argument("--run-id", required=True, help="Experiment run name")
    parser.add_argument(
        "--dataset",
        default="population-search-gold-v2",
        help="Langfuse dataset name",
    )
    parser.add_argument(
        "--tool",
        default=None,
        help="MCP tool name (find_tables | quick_stats | browse_statistics)",
    )
    parser.add_argument(
        "--mode",
        choices=["direct_search", "direct_quick", "direct_list"],
        default=None,
        help="Deprecated alias for --tool",
    )
    parser.add_argument(
        "--cache",
        choices=["bypass", "use"],
        default="bypass",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Parallel items (KOSIS allows 200 calls/min per key)",
    )
    args = parser.parse_args()

    if args.tool and args.mode:
        print("use either --tool or --mode, not both", file=sys.stderr)
        raise SystemExit(1)

    if args.mode:
        cfg = RunConfig.from_mode(
            run_id=args.run_id,
            mode=args.mode,
            cache=args.cache,
            limit=args.limit,
            concurrency=args.concurrency,
        )
    elif args.tool:
        cfg = RunConfig(
            run_id=args.run_id,
            tool=args.tool,  # type: ignore[arg-type]
            cache=args.cache,
            limit=args.limit,
            concurrency=args.concurrency,
        )
    else:
        cfg = RunConfig(
            run_id=args.run_id,
            tool="find_tables",
            cache=args.cache,
            limit=args.limit,
            concurrency=args.concurrency,
        )

    try:
        result = run_experiment(cfg, args.dataset)
    except Exception as exc:
        print(f"experiment failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(result.format())


if __name__ == "__main__":
    main()
