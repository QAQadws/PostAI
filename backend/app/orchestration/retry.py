from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    delay_seconds: float = 0.2,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    last_error: BaseException | None = None
    delay = delay_seconds
    for attempt in range(attempts):
        try:
            return await operation()
        except exceptions as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            if delay > 0:
                await asyncio.sleep(delay)
            delay *= backoff

    assert last_error is not None
    raise last_error

