"""
errors/utils.py — Utility functions for error handling.

Provides helpers for database retry logic and context extraction.
"""

import asyncio
import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from sqlalchemy.exc import OperationalError, TimeoutError

from app.errors.logging import get_logger

logger = get_logger(__name__)


def with_db_retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
) -> Callable:
    """
    Async decorator that adds exponential backoff retry logic for transient
    database errors (like timeouts or operational connection issues).

    Usage:
        @with_db_retry(max_retries=3)
        async def my_db_function():
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            retries = 0
            delay = base_delay

            while True:
                try:
                    return await func(*args, **kwargs)
                except (OperationalError, TimeoutError) as exc:
                    retries += 1
                    if retries > max_retries:
                        logger.error(
                            "Database operation '%s' failed after %d retries.",
                            func.__name__,
                            max_retries,
                        )
                        raise

                    logger.warning(
                        "Transient database error in '%s'. Retrying %d/%d in %.1fs...",
                        func.__name__,
                        retries,
                        max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, max_delay)

        return wrapper

    return decorator
