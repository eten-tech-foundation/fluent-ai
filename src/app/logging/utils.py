"""
logging/utils.py — Logger factory wrapping stdlib logging.

Returns a StructuredLogger (LoggerAdapter subclass) that accepts keyword
arguments as structured fields:  logger.info("msg", key=value)

Use this everywhere; don't construct loggers directly.
"""

import logging
from collections.abc import MutableMapping
from typing import Any


class StructuredLogger(logging.LoggerAdapter):
    """LoggerAdapter that accepts keyword arguments as structured fields.

    Usage::

        logger = StructuredLogger(logging.getLogger(__name__), {})
        logger.info("User created", user_id="u123", role="admin")
        # keyword args are stored in record._structured for formatters.
    """

    _RESERVED = frozenset({"exc_info", "stack_info", "stacklevel", "extra"})

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        structured: dict = dict(self.extra) if self.extra else {}

        # Extract non-reserved kwargs into structured data.
        custom_keys = [k for k in kwargs if k not in self._RESERVED]
        for key in custom_keys:
            structured[key] = kwargs.pop(key)

        extra = kwargs.get("extra", {})
        extra["_structured"] = structured
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> StructuredLogger:
    """Return a structured logger bound to the given name."""
    return StructuredLogger(logging.getLogger(name), {})
