"""get_statistics_data tool."""

from __future__ import annotations

from typing import Any, Literal

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import get_kosis_client
from kosis_mcp.utils.data_formatter import (
    recommend_visualization,
    simplify_statistics_data,
)
from kosis_mcp.utils.meta_lookup import resolve_dimensions, summarize_table_meta


async def get_statistics_data(
    orgId: str,
    tableId: str,
    periodType: Literal["Y", "H", "Q", "M", "D", "F", "IR", "S"],
    regionName: str | None = None,
    itemName: str | None = None,
    objL1: str | None = None,
    objL2: str | None = None,
    objL3: str | None = None,
    objL4: str | None = None,
    itemId: str | None = None,
    startPeriod: str | None = None,
    endPeriod: str | None = None,
    recentCount: int | None = None,
) -> dict[str, Any]:
    client = get_kosis_client()
    cache = get_cache_manager()
    # 반기: 요청 코드는 H (응답 행의 PRD_SE는 S로 온다).
    if periodType == "S":
        periodType = "H"
    try:
        resolved_obj_l1, resolved_obj_l2 = objL1, objL2
        resolved_obj_l3, resolved_obj_l4 = objL3, objL4
        resolved_itm_id = itemId
        resolve_log: list[dict[str, Any]] = []

        needs_lookup = bool(regionName or itemName or (not objL1 and not itemId))
        if needs_lookup:
            r = await resolve_dimensions(
                orgId, tableId, region_name=regionName, item_name=itemName
            )
            if r.get("unmatched"):
                candidate_lines = ""
                if r.get("candidates"):
                    candidate_lines = "\n".join(
                        f"  - {obj_nm}: {', '.join(names[:8])}"
                        + (" ..." if len(names) > 8 else "")
                        for obj_nm, names in r["candidates"].items()
                    )
                miss = ", ".join(
                    filter(
                        None,
                        [
                            f'regionName="{r["unmatched"].get("regionName")}"'
                            if r["unmatched"].get("regionName")
                            else "",
                            f'itemName="{r["unmatched"].get("itemName")}"'
                            if r["unmatched"].get("itemName")
                            else "",
                        ],
                    )
                )
                return {
                    "success": False,
                    "data": [],
                    "totalCount": 0,
                    "metadata": {
                        "orgId": orgId,
                        "tableId": tableId,
                        "periodType": periodType,
                    },
                    "resolved": r.get("resolved"),
                    "usageHint": f"## 메타 lookup 실패\n\n요청한 {miss} 매칭 실패.\n\n### 후보\n{candidate_lines or '(없음)'}",
                }
            resolved_obj_l1 = objL1 or r.get("objL1")
            resolved_obj_l2 = objL2 or r.get("objL2")
            resolved_obj_l3 = objL3 or r.get("objL3")
            resolved_obj_l4 = objL4 or r.get("objL4")
            resolved_itm_id = itemId or r.get("itmId")
            resolve_log = r.get("resolved") or []

        async def fetch():
            return await client.get_statistics_data(
                {
                    "orgId": orgId,
                    "tblId": tableId,
                    "objL1": resolved_obj_l1,
                    "objL2": resolved_obj_l2,
                    "objL3": resolved_obj_l3,
                    "objL4": resolved_obj_l4,
                    "itmId": resolved_itm_id,
                    "prdSe": periodType,
                    "startPrdDe": startPeriod,
                    "endPrdDe": endPeriod,
                    "newEstPrdCnt": recentCount,
                }
            )

        results = await cache.get_statistics_data(
            {
                "orgId": orgId,
                "tableId": tableId,
                "objL1": resolved_obj_l1,
                "objL2": resolved_obj_l2,
                "objL3": resolved_obj_l3,
                "objL4": resolved_obj_l4,
                "itemId": resolved_itm_id,
                "periodType": periodType,
                "startPeriod": startPeriod,
                "endPeriod": endPeriod,
                "recentCount": recentCount,
            },
            fetch,
        )
        if not results:
            return {
                "success": True,
                "data": [],
                "totalCount": 0,
                "metadata": {
                    "orgId": orgId,
                    "tableId": tableId,
                    "periodType": periodType,
                },
                "resolved": resolve_log,
                "usageHint": "데이터를 찾을 수 없습니다. get_table_info로 코드를 확인하세요.",
            }
        simplified = simplify_statistics_data(results)
        periods = [r.get("PRD_DE", "") for r in results]
        period_range = (
            f"{periods[-1]} ~ {periods[0]}" if len(periods) > 1 else periods[0]
        )
        has_multi = len({d.get("classification") for d in simplified}) > 1
        viz = recommend_visualization(
            len(simplified), has_multi, periodType in ("Y", "M", "Q")
        )
        return {
            "success": True,
            "tableName": results[0].get("TBL_NM"),
            "unit": results[0].get("UNIT_NM"),
            "data": simplified,
            "totalCount": len(simplified),
            "visualization": {
                "recommendedType": viz["type"],
                "reason": viz["reason"],
            },
            "metadata": {
                "orgId": orgId,
                "tableId": tableId,
                "periodType": periodType,
                "periodRange": period_range,
            },
        }
    except Exception as error:
        return {
            "success": False,
            "data": [],
            "totalCount": 0,
            "metadata": {
                "orgId": orgId,
                "tableId": tableId,
                "periodType": periodType,
            },
            "usageHint": f"데이터 조회 오류: {error}",
        }

