"""TTL cache — Redis when REDIS_URL is set, else in-memory."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Awaitable, Callable, TypeVar

from kosis_mcp.config import cache_max_keys, cache_ttl_hours, redis_url

T = TypeVar("T")

TTL_STATISTICS_LIST = 24 * 60 * 60
TTL_STATISTICS_DATA = 6 * 60 * 60
TTL_SEARCH_RESULTS = 1 * 60 * 60
TTL_EXPLANATION = 7 * 24 * 60 * 60
TTL_TABLE_META = 24 * 60 * 60
TTL_EMPTY_RESULT = 60

_KEY_PREFIX = "kosis:"


def settle_failed(fut: asyncio.Future[Any], exc: BaseException) -> None:
    """실패한 in-flight future 정리: 취소는 취소로, 예외는 전달하되 '미회수 예외' 로그는 남기지 않는다."""
    if fut.done():
        return
    if isinstance(exc, asyncio.CancelledError):
        fut.cancel()
        return
    fut.set_exception(exc)
    fut.exception()  # 대기자가 없어도 회수된 것으로 표시


class CacheManager:
    def __init__(self, redis_url_value: str | None = None) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self._max_keys = cache_max_keys()
        self._default_ttl = cache_ttl_hours() * 3600
        self._redis_url = redis_url_value
        self._redis: Any | None = None

    async def _r(self) -> Any | None:
        if not self._redis_url:
            return None
        if self._redis is None:
            import redis.asyncio as redis

            self._redis = redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    def _generate_key(self, prefix: str, params: dict[str, Any]) -> str:
        sorted_params = "&".join(
            f"{k}={json.dumps(params[k], ensure_ascii=False, sort_keys=True)}"
            for k in sorted(params)
        )
        return f"{_KEY_PREFIX}{prefix}:{sorted_params}"

    def _mem_get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        value, expires = item
        if time.monotonic() >= expires:
            self._store.pop(key, None)
            return None
        return value

    def _mem_set(self, key: str, value: Any, ttl: int) -> None:
        if len(self._store) >= self._max_keys and key not in self._store:
            # ponytail: drop arbitrary first key when full
            oldest = next(iter(self._store))
            self._store.pop(oldest, None)
        self._store[key] = (value, time.monotonic() + ttl)

    async def _get(self, key: str) -> Any | None:
        r = await self._r()
        if r is None:
            return self._mem_get(key)
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def _set(self, key: str, value: Any, ttl: int) -> None:
        r = await self._r()
        if r is None:
            self._mem_set(key, value, ttl)
            return
        await r.set(key, json.dumps(value, ensure_ascii=False), ex=max(1, ttl))

    async def get_or_fetch(
        self,
        prefix: str,
        params: dict[str, Any],
        fetcher: Callable[[], Awaitable[T]],
        ttl: int | None = None,
    ) -> T:
        if os.getenv("EVAL_CACHE_BYPASS") == "1":
            return await fetcher()

        key = self._generate_key(prefix, params)
        cached = await self._get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        existing = self._inflight.get(key)
        if existing is not None:
            try:
                return await asyncio.shield(existing)  # type: ignore[return-value]
            except asyncio.CancelledError:
                task = asyncio.current_task()
                # 리더가 취소된 경우에만 직접 다시 조회한다(자신이 취소된 경우는 그대로 전파).
                if existing.cancelled() and not (task and task.cancelling()):
                    return await self.get_or_fetch(prefix, params, fetcher, ttl)
                raise

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._inflight[key] = fut
        try:
            data = await fetcher()
            is_empty = isinstance(data, list) and len(data) == 0
            use_ttl = (
                TTL_EMPTY_RESULT
                if is_empty
                else (ttl if ttl is not None else self._default_ttl)
            )
            await self._set(key, data, use_ttl)
            fut.set_result(data)
            return data
        except BaseException as e:
            settle_failed(fut, e)
            raise
        finally:
            self._inflight.pop(key, None)

    async def get_statistics_list(
        self, params: dict[str, Any], fetcher: Callable[[], Awaitable[T]]
    ) -> T:
        return await self.get_or_fetch("list", params, fetcher, TTL_STATISTICS_LIST)

    async def get_statistics_data(
        self, params: dict[str, Any], fetcher: Callable[[], Awaitable[T]]
    ) -> T:
        return await self.get_or_fetch("data", params, fetcher, self._default_ttl)

    async def get_search_results(
        self, params: dict[str, Any], fetcher: Callable[[], Awaitable[T]]
    ) -> T:
        return await self.get_or_fetch(
            "search", params, fetcher, min(TTL_SEARCH_RESULTS, self._default_ttl)
        )

    async def get_explanation(
        self, params: dict[str, Any], fetcher: Callable[[], Awaitable[T]]
    ) -> T:
        return await self.get_or_fetch("explain", params, fetcher, TTL_EXPLANATION)

    async def get_table_meta(
        self, params: dict[str, Any], fetcher: Callable[[], Awaitable[T]]
    ) -> T:
        return await self.get_or_fetch("meta", params, fetcher, TTL_TABLE_META)

    async def flush(self) -> None:
        r = await self._r()
        if r is None:
            self._store.clear()
            return
        async for key in r.scan_iter(match=f"{_KEY_PREFIX}*"):
            await r.delete(key)


_cache: CacheManager | None = None


def get_cache_manager() -> CacheManager:
    global _cache
    if _cache is None:
        _cache = CacheManager(redis_url())
    return _cache
