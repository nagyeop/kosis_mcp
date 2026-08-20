"""get_table_info tool."""

from __future__ import annotations

from typing import Any

from langfuse import get_client
from kosis_mcp.utils.meta_lookup import summarize_table_meta


async def get_table_info(
    orgId: str,
    tableId: str,
    filter: str | None = None,
    sampleSize: int = 10,
) -> dict[str, Any]:
    try:
        summary = await summarize_table_meta(
            orgId, tableId, sample_size=sampleSize or 10, filter=filter
        )
        if not summary["groups"]:
            return {
                "success": False,
                "orgId": orgId,
                "tableId": tableId,
                "usageHint": "메타데이터를 찾을 수 없습니다. orgId와 tableId를 확인하세요.",
            }
        lines = [f"## {orgId} / {tableId} 메타"]
        if filter:
            lines.append(f'(filter="{filter}")\n')
        for g in summary["groups"]:
            label = "[항목]" if g["objIdSn"] == "0" else f"[objL{g['objIdSn']}]"
            lines.append(f"### {label} {g['objNm']} — 총 {g['totalItems']}개")
            for it in g["sample"]:
                lines.append(f"  - `{it['ITM_ID']}` {it['ITM_NM']}")
            if g["totalItems"] > len(g["sample"]):
                lines.append(
                    f"  ... +{g['totalItems'] - len(g['sample'])}개 (filter로 좁히세요)"
                )
        get_client().update_current_span(
            input={"orgId": orgId, "tableId": tableId, "filter": filter},
            metadata={
                "filter": filter,
                "group_count": len(summary["groups"]),
            },
        )
        return {
            "success": True,
            "orgId": orgId,
            "tableId": tableId,
            "groups": summary["groups"],
            "hint": "\n".join(lines),
        }
    except Exception as error:
        msg = str(error)
        return {
            "success": False,
            "orgId": orgId,
            "tableId": tableId,
            "error": msg,
            "usageHint": f"메타 조회 실패: {msg}",
        }
