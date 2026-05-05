"""
logging/formatters.py — Custom log formatters for production and development.

JsonFormatter:  one JSON object per line (production).
DevFormatter:   coloured, human-readable output (development).
"""
import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Produce one JSON object per log line for production."""

    def __init__(self, app_name: str = "", environment: str = "") -> None:
        super().__init__()
        self._app_name = app_name
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if self._app_name:
            log_data["app_name"] = self._app_name
        if self._environment:
            log_data["environment"] = self._environment

        # Request context injected by RequestContextFilter.
        request_id = getattr(record, "request_id", "")
        if request_id:
            log_data["request_id"] = request_id
        correlation_id = getattr(record, "correlation_id", "")
        if correlation_id:
            log_data["correlation_id"] = correlation_id

        # Structured keyword data from StructuredLogger.
        structured = getattr(record, "_structured", {})
        if structured:
            for k, v in structured.items():
                if k not in log_data:
                    log_data[k] = v
                else:
                    log_data[f"extra_{k}"] = v

        # Exception info.
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            log_data["exception"] = record.exc_text

        return json.dumps(log_data, default=str)


class DevFormatter(logging.Formatter):
    """Coloured, human-readable output for development."""

    _COLORS: dict[str, str] = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    _RESET = "\033[0m"
    _DIM = "\033[2m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        reset = self._RESET
        dim = self._DIM

        ts = datetime.fromtimestamp(
            record.created, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S")

        request_id = getattr(record, "request_id", "")
        rid_part = f" {dim}{request_id}{reset}" if request_id else ""

        parts = [
            f"{dim}{ts}{reset}",
            f"{color}{record.levelname:<8}{reset}",
            f"[{dim}{record.name}{reset}]",
            rid_part,
            record.getMessage(),
        ]

        # Append structured keyword data.
        structured = getattr(record, "_structured", {})
        if structured:
            kv = " ".join(f"{dim}{k}{reset}={v}" for k, v in structured.items())
            parts.append(kv)

        line = " ".join(p for p in parts if p)

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            line = f"{line}\n{record.exc_text}"

        return line
