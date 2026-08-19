"""MCP resources."""

from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "data"


def get_category_tree_json() -> str:
    data = json.loads((_DIR / "_category_tree.json").read_text(encoding="utf-8"))
    return json.dumps(data.get("tree", data), ensure_ascii=False, indent=2)


def get_key_indicators_json() -> str:
    data = json.loads((_DIR / "_key_indicators.json").read_text(encoding="utf-8"))
    return json.dumps(data.get("indicators", data), ensure_ascii=False, indent=2)
