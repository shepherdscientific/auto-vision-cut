"""Retry logic with exponential backoff for the AutoVisionCut pipeline."""

import functools
import time
from typing import Any, Callable, TypeVar

from autovideo.logging_setup import get_module_logger

logger = get_module_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            last_exception: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if attempt < max_retries:
                        name = getattr(func, "__name__", "unknown")
                        logger.warning(
                            "Attempt %d/%d failed for %s: %s — retrying in %.1fs",
                            attempt + 1,
                            max_retries + 1,
                            name,
                            exc,
                            delay,
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
            raise last_exception  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
