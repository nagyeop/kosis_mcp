"""Utility unit tests."""

import asyncio

import pytest

from kosis_mcp.cache import CacheManager
from kosis_mcp.utils.concurrency import map_with_concurrency
from kosis_mcp.utils.data_formatter import parse_kosis_number
from kosis_mcp.utils.regions import normalize_province_name
from kosis_mcp.tools.more_tools import extract_year_count


def test_parse_kosis_number():
    assert parse_kosis_number("1,234") == 1234
    assert parse_kosis_number("-5.2") == -5.2
    assert parse_kosis_number("0") == 0
    assert parse_kosis_number("-") is None
    assert parse_kosis_number("...") is None
    assert parse_kosis_number("") is None
    assert parse_kosis_number(None) is None


@pytest.mark.asyncio
async def test_map_with_concurrency_order():
    async def mapper(n, _i):
        await asyncio.sleep(n * 0.01)
        return n * 10

    out = await map_with_concurrency([3, 1, 2], mapper, 2)
    assert out == [30, 10, 20]


@pytest.mark.asyncio
async def test_map_concurrency_limit():
    active = 0
    peak = 0

    async def work(_n, _i):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return True

    await map_with_concurrency(list(range(20)), work, 4)
    assert peak <= 4


@pytest.mark.asyncio
async def test_cache_inflight_dedup():
    cache = CacheManager()
    calls = 0

    async def fetcher():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return [{"v": 1}]

    a, b, c = await asyncio.gather(
        cache.get_or_fetch("t", {"k": 1}, fetcher),
        cache.get_or_fetch("t", {"k": 1}, fetcher),
        cache.get_or_fetch("t", {"k": 1}, fetcher),
    )
    assert calls == 1
    assert a is b is c


@pytest.mark.asyncio
async def test_cache_hit():
    cache = CacheManager()
    calls = 0

    async def fetcher():
        nonlocal calls
        calls += 1
        return [1, 2]

    await cache.get_or_fetch("t", {"k": 2}, fetcher)
    await cache.get_or_fetch("t", {"k": 2}, fetcher)
    assert calls == 1


def test_normalize_province():
    assert normalize_province_name("전라북도") == "전북"
    assert normalize_province_name("강원특별자치도") == "강원"
    assert normalize_province_name("서울") == "서울"


def test_extract_year_count_basic():
    assert extract_year_count("지난 10년") == 10
