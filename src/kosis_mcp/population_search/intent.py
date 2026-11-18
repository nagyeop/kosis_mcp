"""classify_population_intent — rule-based intent gate."""

from __future__ import annotations

import re
from typing import Any, Literal

PopulationIntent = Literal["find_table", "get_value", "clarify", "browse"]

_FIND_HINTS = re.compile(
    r"표\s*찾|통계표|어떤\s*표|볼\s*수\s*있|찾아\s*줘|찾아줘|추천.*표"
)
_VALUE_HINTS = re.compile(
    r"얼마|몇\s*명|알려\s*줘|알려줘|수치|값|조회해|보여\s*줘"
)
_CLARIFY_HINTS = re.compile(
    r"노인|애들|어린이|어디에|어느\s*쪽|무슨\s*기준"
)
_BROWSE_HINTS = re.compile(r"목록|둘러|추천\s*카드|주제별")


async def classify_population_intent(query: str) -> dict[str, Any]:
    if _CLARIFY_HINTS.search(query):
        intent: PopulationIntent = "clarify"
    elif _FIND_HINTS.search(query):
        intent = "find_table"
    elif _VALUE_HINTS.search(query) and not _FIND_HINTS.search(query):
        intent = "get_value"
    elif _BROWSE_HINTS.search(query):
        intent = "browse"
    else:
        intent = "find_table"
    return {"success": True, "query": query, "intent": intent}
