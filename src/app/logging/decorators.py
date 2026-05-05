"""
logging/decorators.py — Function-level logging decorators.
"""
import functools
import inspect
import time
from collections.abc import Callable
from typing import Any

from app.logging.utils import get_logger


def log_call(logger: Any = None, level: str = "debug") -> Callable:
    """Decorator factory that logs function entry, exit, and exceptions.

    Works on both async and sync functions. Never logs argument values.
    """

    def decorator(func: Callable) -> Callable:
        log = logger or get_logger(func.__module__)
        log_fn = getattr(log, level.lower())

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                log_fn(
                    "Function called",
                    function=func.__qualname__,
                    module=func.__module__,
                    args_count=len(args),
                    kwargs_keys=list(kwargs.keys()),
                )
                start = time.monotonic()
                try:
                    result = await func(*args, **kwargs)
                    duration_ms = round((time.monotonic() - start) * 1000, 2)
                    log_fn(
                        "Function returned",
                        function=func.__qualname__,
                        duration_ms=duration_ms,
                    )
                    return result
                except Exception as exc:
                    duration_ms = round((time.monotonic() - start) * 1000, 2)
                    log.error(
                        "Function failed",
                        function=func.__qualname__,
                        error=type(exc).__name__,
                        duration_ms=duration_ms,
                    )
                    raise
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                log_fn(
                    "Function called",
                    function=func.__qualname__,
                    module=func.__module__,
                    args_count=len(args),
                    kwargs_keys=list(kwargs.keys()),
                )
                start = time.monotonic()
                try:
                    result = func(*args, **kwargs)
                    duration_ms = round((time.monotonic() - start) * 1000, 2)
                    log_fn(
                        "Function returned",
                        function=func.__qualname__,
                        duration_ms=duration_ms,
                    )
                    return result
                except Exception as exc:
                    duration_ms = round((time.monotonic() - start) * 1000, 2)
                    log.error(
                        "Function failed",
                        function=func.__qualname__,
                        error=type(exc).__name__,
                        duration_ms=duration_ms,
                    )
                    raise
            return sync_wrapper

    return decorator


def log_performance(threshold_ms: float = 500, level: str = "warning") -> Callable:
    """Decorator factory that logs when execution exceeds a time threshold.

    Only emits a log when duration_ms > threshold_ms. Does not catch exceptions.
    """

    def decorator(func: Callable) -> Callable:
        log = get_logger(func.__module__)
        log_fn = getattr(log, level.lower())

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.monotonic()
                result = await func(*args, **kwargs)
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                if duration_ms > threshold_ms:
                    log_fn(
                        "Performance threshold exceeded",
                        function=func.__qualname__,
                        duration_ms=duration_ms,
                        threshold_ms=threshold_ms,
                    )
                return result
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.monotonic()
                result = func(*args, **kwargs)
                duration_ms = round((time.monotonic() - start) * 1000, 2)
                if duration_ms > threshold_ms:
                    log_fn(
                        "Performance threshold exceeded",
                        function=func.__qualname__,
                        duration_ms=duration_ms,
                        threshold_ms=threshold_ms,
                    )
                return result
            return sync_wrapper

    return decorator
