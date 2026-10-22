"""
logging/filters.py — Scrub sensitive data and inject request context.

Contains:
  - Data sanitisation helpers (scrub_dict, scrub_url, scrub_text, mask_email)
  - RequestContextFilter  — injects request_id / correlation_id into records
  - SensitiveDataFilter   — scrubs _structured dict on every record
"""

import logging
import re
import urllib.parse
from typing import Any

_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "x-api-key",
        "key_hash",
        "raw_key",
        "credit_card",
        "ssn",
        "access_token",
        "refresh_token",
        "private_key",
    }
)

_SENSITIVE_QUERY_PARAMS: frozenset[str] = frozenset(
    {
        "token",
        "key",
        "secret",
        "password",
        "api_key",
    }
)

_EMAIL_RE = re.compile(r"^([^@]+)(@.+)$")

# A credential value embedded in free text ends at whitespace, a quote, or the
# punctuation that delimits it in URLs, headers and exception reprs.
_TEXT_VALUE = r"[^\s\"'&;,)]+"
# Names too generic to match as the tail of a longer identifier: `dedup_key`
# or `monkey` must not count as a `key`.
_EXACT_TEXT_NAMES: frozenset[str] = frozenset({"key", "ssn"})


def _text_name_pattern(names: frozenset[str]) -> str:
    # Separators are optional and interchangeable, so `api_key` also matches
    # `api-key` and `apiKey`.
    return "|".join(
        re.sub(r"[_-]", "[_-]?", re.escape(name))
        for name in sorted(names, key=len, reverse=True)
    )


_SENSITIVE_TEXT_NAMES = _SENSITIVE_KEYS | _SENSITIVE_QUERY_PARAMS
_SENSITIVE_TEXT_ASSIGNMENT_RE = re.compile(
    # A credential name may carry any identifier prefix (`client_secret`,
    # `x-goog-api-key`), except the generic exact names.
    r"\b((?:[\w-]*?(?:"
    + _text_name_pattern(_SENSITIVE_TEXT_NAMES - _EXACT_TEXT_NAMES)
    + r"))|(?:"
    + _text_name_pattern(_EXACT_TEXT_NAMES)
    + r"))([\"']?\s*[:=]\s*[\"']?)((?:bearer|basic)\s+)?"
    + _TEXT_VALUE,
    re.IGNORECASE,
)
_BEARER_TOKEN_RE = re.compile(
    r"\b(bearer|basic)\s+(?!\[REDACTED\])" + _TEXT_VALUE, re.IGNORECASE
)


# --------------------------------------------------------------------------- #
# Data sanitisation helpers
# --------------------------------------------------------------------------- #


def scrub_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with sensitive values redacted."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = scrub_dict(value)
        elif isinstance(value, list):
            result[key] = [
                scrub_dict(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            result[key] = value
    return result


def scrub_url(url: str) -> str:
    """Parse URL and redact sensitive query parameter values."""
    try:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        scrubbed_query = [
            (k, "[REDACTED]" if k.lower() in _SENSITIVE_QUERY_PARAMS else v)
            for k, v in query
        ]
        new_query = urllib.parse.urlencode(scrubbed_query)
        new_parsed = parsed._replace(query=new_query)
        return urllib.parse.urlunparse(new_parsed)
    except Exception:
        return url


def scrub_text(text: str) -> str:
    """Redact credential-looking `name=value` / `name: value` pairs and bearer
    tokens in free text, such as an upstream error message."""
    text = _SENSITIVE_TEXT_ASSIGNMENT_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3) or ''}[REDACTED]", text
    )
    return _BEARER_TOKEN_RE.sub(lambda m: f"{m.group(1)} [REDACTED]", text)


def mask_email(email: str) -> str:
    """Mask email address to show only first character of username."""
    match = _EMAIL_RE.match(email)
    if match:
        username, domain = match.groups()
        return f"{username[0]}***{domain}"
    return email


# --------------------------------------------------------------------------- #
# stdlib logging Filters
# --------------------------------------------------------------------------- #


class RequestContextFilter(logging.Filter):
    """Inject request_id and correlation_id from ContextVar into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        from app.logging.context import get_correlation_id, get_request_id

        record.request_id = get_request_id()
        record.correlation_id = get_correlation_id()
        return True


class SensitiveDataFilter(logging.Filter):
    """Scrub sensitive fields from structured data attached by StructuredLogger."""

    def filter(self, record: logging.LogRecord) -> bool:
        structured = getattr(record, "_structured", None)
        if structured and isinstance(structured, dict):
            record._structured = scrub_dict(structured)
        return True
