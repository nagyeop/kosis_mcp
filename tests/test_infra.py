"""L2 tests for cache in-flight handling and the KOSIS rate limiter."""

import asyncio
import gc

import pytest

from kosis_mcp.cache import CacheManager
from kosis_mcp.client import RateLimiter


async def test_waiter_recovers_when_leader_is_cancelled():
    cache = CacheManager(None)
    started = asyncio.Event()
    calls = 0

    async def slow():
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.sleep(10)
        return ["slow"]

    async def fast():
        nonlocal calls
        calls += 1
        return ["fast"]

    leader = asyncio.create_task(cache.get_or_fetch("t", {"k": 1}, slow))
    await started.wait()
    waiter = asyncio.create_task(cache.get_or_fetch("t", {"k": 1}, fast))
    await asyncio.sleep(0)
    leader.cancel()
    assert await asyncio.wait_for(waiter, 1) == ["fast"]
    with pytest.raises(asyncio.CancelledError):
        await leader


async def test_failed_fetch_without_waiters_logs_nothing(caplog):
    cache = CacheManager(None)

    async def boom():
        raise ValueError("x")

    with pytest.raises(ValueError):
        await cache.get_or_fetch("t", {"k": 2}, boom)
    gc.collect()
    await asyncio.sleep(0)
    assert "never retrieved" not in caplog.text


async def test_rate_limiter_blocks_over_budget():
    limiter = RateLimiter(rpm=2, window=0.2)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    for _ in range(3):
        await limiter.acquire()
    assert loop.time() - t0 >= 0.19
