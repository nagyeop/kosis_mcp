"""KOSIS OpenAPI HTTP client."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from langfuse import get_client, observe

from kosis_mcp.config import KOSIS_BASE_URL, KOSIS_ENDPOINTS, get_api_key


class KosisApiError(Exception):
    def __init__(self, code: str, message: str, original: Exception | None = None):
        super().__init__(message)
        self.code = code
        self.original = original


class KosisClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.base_url = KOSIS_BASE_URL
        self.api_key = api_key or get_api_key()

    @observe(name="kosis.openapi.request", as_type="retriever")
    async def _request(
        self, endpoint: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        clean: dict[str, str] = {
            k: str(v) for k, v in params.items() if v is not None
        }
        clean["apiKey"] = self.api_key
        clean["format"] = "json"
        clean["jsonVD"] = "Y"

        url = f"{self.base_url}{endpoint}"
        timeout = 15.0
        max_attempts = 3
        trace_input = {
            "url": url,
            "endpoint": endpoint,
            "params": {k: v for k, v in clean.items() if k != "apiKey"},
        }

        last_err: Exception | None = None
        for attempt in range(max_attempts):
            is_retryable = False
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=clean)

                if response.status_code >= 500:
                    is_retryable = True
                    raise KosisApiError(
                        "HTTP_ERROR",
                        f"HTTP {response.status_code}: {response.reason_phrase}",
                    )
                if response.status_code >= 400:
                    raise KosisApiError(
                        "HTTP_ERROR",
                        f"HTTP {response.status_code}: {response.reason_phrase}",
                    )

                data = response.json()
                if isinstance(data, dict) and (data.get("err") or data.get("errMsg")):
                    raise KosisApiError(
                        str(data.get("err") or "API_ERROR"),
                        str(data.get("errMsg") or "알 수 없는 API 오류"),
                    )

                if isinstance(data, list):
                    rows = data
                elif isinstance(data, dict):
                    if isinstance(data.get("result"), list):
                        rows = data["result"]
                    elif data:
                        rows = [data]
                    else:
                        rows = []
                else:
                    rows = []

                get_client().update_current_span(
                    input=trace_input,
                    output={
                        "row_count": len(rows),
                        "rows": rows[:10],
                        "truncated": len(rows) > 10,
                    },
                    metadata={
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                    },
                )
                return rows
            except KosisApiError as e:
                if not is_retryable:
                    get_client().update_current_span(
                        input=trace_input,
                        metadata={
                            "attempt": attempt + 1,
                            "error": str(e)[:200],
                        },
                        level="ERROR",
                    )
                    raise
                last_err = e
            except httpx.TimeoutException as e:
                last_err = e
                is_retryable = True
            except httpx.HTTPError as e:
                last_err = e
                is_retryable = True

            if attempt == max_attempts - 1:
                err_msg = str(last_err)[:200] if last_err else "unknown"
                get_client().update_current_span(
                    input=trace_input,
                    metadata={"attempt": attempt + 1, "error": err_msg},
                    level="ERROR",
                )
                if isinstance(last_err, httpx.TimeoutException):
                    raise KosisApiError(
                        "TIMEOUT",
                        f"KOSIS API 응답 시간 초과 ({int(timeout)}초, {max_attempts}회 시도). "
                        "잠시 후 다시 시도해주세요.",
                    ) from last_err
                if isinstance(last_err, KosisApiError):
                    raise last_err
                raise KosisApiError(
                    "NETWORK_ERROR", "네트워크 오류가 발생했습니다.", last_err
                ) from last_err
            await asyncio.sleep(0.8 * (attempt + 1))

        get_client().update_current_span(
            input=trace_input,
            metadata={"error": "UNEXPECTED"},
            level="ERROR",
        )
        raise KosisApiError("UNEXPECTED", "요청 처리 중 예기치 못한 종료")

    async def get_statistics_list(
        self, vw_cd: str, parent_list_id: str = ""
    ) -> list[dict[str, Any]]:
        return await self._request(
            KOSIS_ENDPOINTS["statistics_list"],
            {"method": "getList", "vwCd": vw_cd, "parentListId": parent_list_id},
        )

    async def get_statistics_data(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._request(
            KOSIS_ENDPOINTS["parameter_data"],
            {"method": "getList", **params},
        )

    async def search_statistics(
        self,
        search_nm: str,
        *,
        org_id: str | None = None,
        sort: str | None = None,
        start_count: int | None = None,
        result_count: int | None = None,
    ) -> list[dict[str, Any]]:
        p: dict[str, Any] = {"method": "getList", "searchNm": search_nm}
        if org_id is not None:
            p["orgId"] = org_id
        if sort is not None:
            p["sort"] = sort
        if start_count is not None:
            p["startCount"] = start_count
        if result_count is not None:
            p["resultCount"] = result_count
        return await self._request(KOSIS_ENDPOINTS["search_statistics"], p)

    async def get_statistics_explain(
        self, org_id: str, tbl_id: str
    ) -> list[dict[str, Any]]:
        return await self._request(
            KOSIS_ENDPOINTS["stats_explain"],
            {
                "method": "getList",
                "orgId": org_id,
                "tblId": tbl_id,
                "metaItm": "All",
            },
        )

    async def get_table_meta(
        self,
        org_id: str,
        tbl_id: str,
        meta_type: str = "ITM",
    ) -> list[dict[str, Any]]:
        return await self._request(
            KOSIS_ENDPOINTS["statistics_data"],
            {
                "method": "getMeta",
                "type": meta_type,
                "orgId": org_id,
                "tblId": tbl_id,
            },
        )


_client: KosisClient | None = None


def get_kosis_client() -> KosisClient:
    global _client
    if _client is None:
        _client = KosisClient()
    return _client
