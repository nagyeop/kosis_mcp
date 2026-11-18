#!/usr/bin/env python3
"""Upload a testset JSON file to a Langfuse dataset (create_dataset_item upserts by id)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from langfuse import Langfuse

ROOT = Path(__file__).resolve().parents[2]
TESTSET = ROOT / "tests" / "testset"
# v2: exclude 항목 분리(routing_excluded_queries.json), scope_category 라벨 추가
DATASETS: dict[str, Path] = {
    "population-search-gold-v2": TESTSET / "gold_queries.json",
    "population-search-ops-gold-v2": TESTSET / "ops_gold_queries.json",
    "population-search-edge-v2": TESTSET / "edge_queries.json",
}


def upload_dataset(
    dataset_name: str,
    *,
    source: Path | None = None,
    dry_run: bool = False,
) -> None:
    load_dotenv()
    path = source or DATASETS.get(dataset_name)
    if path is None:
        raise SystemExit(
            f"unknown dataset {dataset_name!r}; pass --source or use: "
            + ", ".join(DATASETS)
        )
    rows = json.loads(path.read_text(encoding="utf-8"))
    if dry_run:
        print(f"dry-run: would upload {len(rows)} items from {path.name} to {dataset_name}")
        return

    langfuse = Langfuse()
    try:
        try:
            langfuse.create_dataset(name=dataset_name)
            print(f"created dataset: {dataset_name}")
        except Exception:
            print(f"dataset exists: {dataset_name}")

        for row in rows:
            query_id = row["query_id"]
            langfuse.create_dataset_item(
                dataset_name=dataset_name,
                # item ids are unique per Langfuse project across datasets
                id=f"{dataset_name}:{query_id}",
                input={
                    "query": row["query"],
                    "query_id": query_id,
                    "category": row.get("scope_category"),
                },
                expected_output={
                    "expected_action": row["expected_action"],
                    "gold_table_ids": row["gold_table_ids"],
                    "primary_gold_table_id": row.get("primary_gold_table_id") or "",
                    "hard_negative_ids": row.get("hard_negative_ids") or [],
                },
                metadata={
                    "query_group": row.get("query_group"),
                    "validation_status": row.get("validation_status"),
                    "review_confidence": row.get("review_confidence"),
                    "review_note": row.get("review_note"),
                    "evidence_source": row.get("evidence_source"),
                },
            )

        print(f"upserted {len(rows)} items from {path.name} → {dataset_name}")
    finally:
        langfuse.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload gold queries to Langfuse dataset")
    parser.add_argument(
        "--dataset",
        default="population-search-gold-v2",
        help="Langfuse dataset name",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="testset JSON path (default: mapped from --dataset)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    upload_dataset(args.dataset, source=args.source, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
