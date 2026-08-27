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
        default="population-search-gold-v1",
        help="Langfuse dataset name",
    )
    parser.add_argument(
        "--mode",
        choices=["direct_search", "direct_quick", "direct_list"],
        default="direct_search",
    )
    parser.add_argument(
        "--cache",
        choices=["bypass", "use"],
        default="bypass",
    )
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    try:
        result = run_experiment(
            RunConfig(
                run_id=args.run_id,
                mode=args.mode,
                cache=args.cache,
                limit=args.limit,
            ),
            args.dataset,
        )
    except Exception as exc:
        print(f"experiment failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    # Averages + dataset run URL come from Langfuse ExperimentResult.format()
    print(result.format())


if __name__ == "__main__":
    main()
