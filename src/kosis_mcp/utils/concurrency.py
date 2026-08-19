"""Async concurrency-limited map."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")

CHAIN_CONCURRENCY = 8


async def map_with_concurrency(
    items: Sequence[T],
    mapper: Callable[[T, int], Awaitable[R]],
    concurrency: int,
) -> list[R]:
    results: list[R | None] = [None] * len(items)
    next_i = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal next_i
        while True:
            async with lock:
                if next_i >= len(items):
                    return
                i = next_i
                next_i += 1
            results[i] = await mapper(items[i], i)

    workers = [
        asyncio.create_task(worker())
        for _ in range(max(1, min(concurrency, len(items) or 1)))
    ]
    await asyncio.gather(*workers)
    return results  # type: ignore[return-value]
