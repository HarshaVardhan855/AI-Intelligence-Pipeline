import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def retry_async(operation: Callable[[], Awaitable[T]], retries: int = 4, retryable: tuple[type[Exception], ...] = (Exception,)) -> T:
    for attempt in range(retries):
        try:
            return await operation()
        except retryable:
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2 ** attempt + random.uniform(0, 0.4))
    raise RuntimeError("unreachable")
