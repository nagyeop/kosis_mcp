"""Natural-language query parser for KOSIS search."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_DATA = json.loads(
    (
        Path(__file__).resolve().parent.parent / "data" / "_query_parser.json"
    ).read_text(encoding="utf-8")
)

TOPIC_MAPPINGS: dict[str, dict[str, Any]] = _DATA["TOPIC_MAPPINGS"]
REGION_CODES: dict[str, str] = _DATA["REGION_CODES"]
REGION_NAMES: dict[str, str] = _DATA["REGION_NAMES"]

TIME_PATTERNS = [
    {"pattern": re.compile(r"최근\s*(\d+)\s*년"), "type": "recent_years"},
    {"pattern": re.compile(r"(\d{4})년"), "type": "specific_year"},
    {"pattern": re.compile(r"올해|금년"), "type": "this_year"},
    {"pattern": re.compile(r"작년|전년|지난해"), "type": "last_year"},
    {"pattern": re.compile(r"(\d{4})\s*~\s*(\d{4})"), "type": "year_range"},
]


def parse_query(query: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "topics": [],
        "regions": [],
        "keywords": [],
        "intent": "search",
    }
    lower_query = query.lower()

    for keyword, mapping in TOPIC_MAPPINGS.items():
        if keyword in query:
            result["topics"].append(mapping["category"])
            result["keywords"].extend(mapping["keywords"])

    for region_name, code in REGION_CODES.items():
        if region_name in query:
            result["regions"].append(code)

    for item in TIME_PATTERNS:
        match = item["pattern"].search(query)
        if not match:
            continue
        t = item["type"]
        if t == "recent_years":
            result["timeRange"] = {"type": "recent", "value": int(match.group(1))}
        elif t == "specific_year":
            result["timeRange"] = {
                "type": "specific",
                "start": match.group(1),
                "end": match.group(1),
            }
        elif t == "this_year":
            y = str(datetime.now().year)
            result["timeRange"] = {"type": "specific", "start": y, "end": y}
        elif t == "last_year":
            y = str(datetime.now().year - 1)
            result["timeRange"] = {"type": "specific", "start": y, "end": y}
        elif t == "year_range":
            result["timeRange"] = {
                "type": "range",
                "start": match.group(1),
                "end": match.group(2),
            }
        break

    if "비교" in lower_query or "차이" in lower_query or "vs" in lower_query:
        result["intent"] = "compare"
    elif "추세" in lower_query or "변화" in lower_query or "추이" in lower_query:
        result["intent"] = "trend"
    elif "뭐" in lower_query or "무엇" in lower_query or "설명" in lower_query:
        result["intent"] = "explain"

    if not result["keywords"]:
        result["keywords"] = [w for w in re.split(r"\s+", query) if len(w) > 1]

    result["topics"] = list(dict.fromkeys(result["topics"]))
    result["keywords"] = list(dict.fromkeys(result["keywords"]))
    return result


def generate_search_terms(
    parsed: dict[str, Any], original_query: str | None = None
) -> list[str]:
    terms: list[str] = []
    if parsed["regions"]:
        region_names = [
            REGION_NAMES[code] for code in parsed["regions"] if code in REGION_NAMES
        ]
        topic_keywords = parsed["keywords"][:2]
        for region in region_names:
            for keyword in topic_keywords:
                terms.append(f"{region} {keyword}")
        terms.extend(region_names)
    terms.extend(parsed["keywords"][:3])
    return list(dict.fromkeys(terms))
