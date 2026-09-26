import asyncio
import random
import time
from typing import Callable, TypeVar, Any, Optional
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Synchronous retry function with exponential backoff and jitter."""
    attempts = 0
    while True:
        try:
            return func()
        except retryable_exceptions as e:
            attempts += 1
            if attempts > max_retries:
                logger.error("Max retries (%d) exceeded: %s", max_retries, e)
                raise e

            delay = min(base_delay * (exponential_base ** (attempts - 1)), max_delay)
            if jitter:
                delay = delay * (0.5 + random.random() * 0.5)

            logger.warning(
                "Attempt %d/%d failed with %s: %s. Retrying in %.2fs...",
                attempts,
                max_retries,
                type(e).__name__,
                e,
                delay,
            )
            time.sleep(delay)


async def async_retry_with_backoff(
    func: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Any:
    """Asynchronous retry function with exponential backoff and jitter."""
    attempts = 0
    while True:
        try:
            res = func()
            if asyncio.iscoroutine(res):
                return await res
            return res
        except retryable_exceptions as e:
            attempts += 1
            if attempts > max_retries:
                logger.error("Max retries (%d) exceeded: %s", max_retries, e)
                raise e

            delay = min(base_delay * (exponential_base ** (attempts - 1)), max_delay)
            if jitter:
                delay = delay * (0.5 + random.random() * 0.5)

            logger.warning(
                "Async attempt %d/%d failed with %s: %s. Retrying in %.2fs...",
                attempts,
                max_retries,
                type(e).__name__,
                e,
                delay,
            )
            await asyncio.sleep(delay)
