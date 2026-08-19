"""analyze_time_series / compare_statistics / get_statistics_data tools."""

from __future__ import annotations

from typing import Any, Literal

from kosis_mcp.cache import get_cache_manager
from kosis_mcp.client import get_kosis_client
from kosis_mcp.utils.data_formatter import (
    analyze_trend,
    calculate_change_rate,
    format_period,
    parse_kosis_number,
    recommend_visualization,
    simplify_statistics_data,
)
from kosis_mcp.utils.meta_lookup import resolve_dimensions, summarize_table_meta


def _trend_description(trend: str) -> str:
    return {
        "increasing": "지속적인 상승 추세를 보이고 있습니다.",
        "decreasing": "지속적인 하락 추세를 보이고 있습니다.",
        "stable": "안정적인 흐름을 유지하고 있습니다.",
        "fluctuating": "변동이 큰 불안정한 흐름을 보이고 있습니다.",
    }.get(trend, "추세를 파악하기 어렵습니다.")


async def get_statistics_data(
    orgId: str,
    tableId: str,
    periodType: Literal["Y", "M", "Q", "S", "D", "F", "IR"],
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


async def analyze_time_series(
    orgId: str,
    tableId: str,
    objL1: str,
    itemId: str,
    periodType: Literal["Y", "M", "Q"],
    objL2: str | None = None,
    yearCount: int = 10,
) -> dict[str, Any]:
    client = get_kosis_client()
    cache = get_cache_manager()
    try:
        results = await cache.get_statistics_data(
            {
                "orgId": orgId,
                "tableId": tableId,
                "objL1": objL1,
                "objL2": objL2,
                "itemId": itemId,
                "periodType": periodType,
                "yearCount": yearCount,
            },
            lambda: client.get_statistics_data(
                {
                    "orgId": orgId,
                    "tblId": tableId,
                    "objL1": objL1,
                    "objL2": objL2,
                    "itmId": itemId,
                    "prdSe": periodType,
                    "newEstPrdCnt": yearCount,
                }
            ),
        )
        sorted_data = sorted(
            [
                {
                    "period": r["PRD_DE"],
                    "value": parse_kosis_number(r.get("DT")),
                    "formatted": r.get("DT"),
                }
                for r in results
            ],
            key=lambda d: d["period"],
        )
        sorted_data = [d for d in sorted_data if d["value"] is not None]
        if len(sorted_data) < 2:
            return {
                "success": True,
                "dataPoints": [],
                "interpretation": [
                    "분석에 필요한 충분한 데이터가 없습니다.",
                    "get_table_info로 유효한 분류/항목 코드를 확인하세요.",
                ],
            }
        values = [float(d["value"]) for d in sorted_data]
        trend_info = analyze_trend(values)
        max_idx = values.index(max(values))
        min_idx = values.index(min(values))
        last_v, prev_v = values[-1], values[-2]
        recent = ((last_v - prev_v) / abs(prev_v) * 100) if prev_v != 0 else 0.0
        analysis = {
            "trend": trend_info["trend"],
            "trendDescription": _trend_description(trend_info["trend"]),
            "averageGrowthRate": round(trend_info["avgGrowthRate"], 2),
            "volatility": round(trend_info["volatility"], 2),
            "maxValue": {
                "period": format_period(sorted_data[max_idx]["period"], periodType),
                "value": sorted_data[max_idx]["value"],
                "formatted": sorted_data[max_idx]["formatted"],
            },
            "minValue": {
                "period": format_period(sorted_data[min_idx]["period"], periodType),
                "value": sorted_data[min_idx]["value"],
                "formatted": sorted_data[min_idx]["formatted"],
            },
            "recentChange": {
                "rate": round(recent, 2),
                "direction": "up"
                if recent > 0.1
                else "down"
                if recent < -0.1
                else "stable",
                "formatted": f"{'+' if recent > 0 else ''}{recent:.1f}%",
            },
        }
        if trend_info["trend"] == "increasing":
            analysis["forecast"] = "현재 추세가 지속된다면 향후 지속적인 증가가 예상됩니다."
        elif trend_info["trend"] == "decreasing":
            analysis["forecast"] = "현재 추세가 지속된다면 향후 지속적인 감소가 예상됩니다."
        interpretation = [
            f"📊 **추세**: {analysis['trendDescription']}",
            f"📈 **평균 성장률**: {'+' if analysis['averageGrowthRate'] > 0 else ''}{analysis['averageGrowthRate']}%",
            f"🔝 **최고점**: {analysis['maxValue']['period']} ({analysis['maxValue']['formatted']})",
            f"🔻 **최저점**: {analysis['minValue']['period']} ({analysis['minValue']['formatted']})",
            f"📅 **최근 변화**: {analysis['recentChange']['formatted']}",
        ]
        if trend_info["volatility"] > 20:
            interpretation.append(
                f"⚠️ **주의**: 변동성이 높습니다 ({trend_info['volatility']:.1f}%)."
            )
        if analysis.get("forecast"):
            interpretation.append(f"🔮 **전망**: {analysis['forecast']}")
        return {
            "success": True,
            "tableName": results[0].get("TBL_NM"),
            "unit": results[0].get("UNIT_NM"),
            "analysis": analysis,
            "dataPoints": [
                {
                    "period": format_period(d["period"], periodType),
                    "value": d["value"],
                }
                for d in sorted_data
            ],
            "interpretation": interpretation,
        }
    except Exception as error:
        return {
            "success": False,
            "dataPoints": [],
            "interpretation": [f"시계열 분석 오류: {error}"],
        }


async def compare_statistics(
    orgId: str,
    tableId: str,
    compareType: Literal["period", "item"],
    periodType: Literal["Y", "M", "Q"],
    periods: list[str] | None = None,
    objL1: str | None = None,
    objL2: str | None = None,
    itemId: str | None = None,
) -> dict[str, Any]:
    client = get_kosis_client()
    cache = get_cache_manager()
    try:

        async def fetch():
            if compareType == "period" and periods:
                all_results = []
                for period in periods:
                    data = await client.get_statistics_data(
                        {
                            "orgId": orgId,
                            "tblId": tableId,
                            "objL1": objL1 or "ALL",
                            "objL2": objL2,
                            "itmId": itemId or "ALL",
                            "prdSe": periodType,
                            "startPrdDe": period,
                            "endPrdDe": period,
                        }
                    )
                    all_results.extend(data)
                return all_results
            return await client.get_statistics_data(
                {
                    "orgId": orgId,
                    "tblId": tableId,
                    "objL1": objL1 or "ALL",
                    "objL2": objL2,
                    "itmId": "ALL",
                    "prdSe": periodType,
                    "newEstPrdCnt": 1,
                }
            )

        results = await cache.get_statistics_data(
            {
                "orgId": orgId,
                "tableId": tableId,
                "compareType": compareType,
                "periods": periods,
            },
            fetch,
        )
        if not results:
            return {
                "success": True,
                "compareType": compareType,
                "items": [],
                "summary": "비교할 데이터가 없습니다.",
                "insights": [],
            }
        valid = [r for r in results if parse_kosis_number(r.get("DT")) is not None]
        dropped = len(results) - len(valid)
        if not valid:
            return {
                "success": True,
                "compareType": compareType,
                "items": [],
                "summary": "비교할 수치 데이터가 없습니다 (조회된 행이 모두 결측).",
                "insights": [],
            }
        items: list[dict[str, Any]] = []
        for r in valid:
            value = parse_kosis_number(r.get("DT"))
            region = r.get("C1_NM") or None
            item_name = r.get("ITM_NM") or None
            period = r.get("PRD_DE") or None
            name = (
                period or "N/A"
                if compareType == "period"
                else " - ".join(x for x in [region, item_name] if x) or "N/A"
            )
            items.append(
                {
                    "name": name,
                    "region": region,
                    "itemName": item_name,
                    "period": period,
                    "value": value,
                    "formattedValue": r.get("DT"),
                    "unit": r.get("UNIT_NM"),
                }
            )
        sorted_items = sorted(items, key=lambda i: i["value"], reverse=True)
        for idx, item in enumerate(sorted_items):
            for original in items:
                if original["name"] == item["name"]:
                    original["rank"] = idx + 1
        if compareType == "period" and len(items) > 1:
            for i in range(1, len(items)):
                items[i]["change"] = calculate_change_rate(
                    items[i]["value"], items[i - 1]["value"]
                )
        max_item, min_item = sorted_items[0], sorted_items[-1]
        summary = (
            f"{items[0]['name']}부터 {items[-1]['name']}까지의 변화를 비교했습니다."
            if compareType == "period"
            else f'총 {len(items)}개 항목 중 "{max_item["name"]}"이(가) 가장 높고, "{min_item["name"]}"이(가) 가장 낮습니다.'
        )
        insights: list[str] = []
        if compareType == "period":
            total = calculate_change_rate(items[-1]["value"], items[0]["value"])
            insights.append(
                f"전체 기간 동안 "
                f"{'증가' if total['direction'] == 'up' else '감소' if total['direction'] == 'down' else '변동 없음'} "
                f"({total['formatted']})"
            )
        else:
            diff = (
                f"{(max_item['value'] - min_item['value']) / abs(min_item['value']) * 100:.1f}"
                if min_item["value"] != 0
                else "N/A"
            )
            insights.append(f"최대-최소 차이: {diff}%")
        if dropped:
            insights.append(f"ℹ️ 결측·비수치 {dropped}건은 비교에서 제외했습니다.")
        return {
            "success": True,
            "compareType": compareType,
            "items": items,
            "summary": summary,
            "insights": insights,
        }
    except Exception as error:
        return {
            "success": False,
            "compareType": compareType,
            "items": [],
            "summary": "비교 중 오류가 발생했습니다.",
            "insights": [str(error)],
        }
