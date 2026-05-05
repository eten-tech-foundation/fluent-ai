"""
logging/config.py — One-time logging setup for the whole application.

Call configure_logging(settings) before FastAPI app creation in main.py.
Uses only Python's stdlib logging module — no third-party dependencies.
"""
import logging
import logging.handlers
import sys

from app.config import Settings
from app.logging.filters import RequestContextFilter, SensitiveDataFilter
from app.logging.formatters import DevFormatter, JsonFormatter

_configured: bool = False


def configure_logging(settings: Settings) -> None:
    """Configure the root logger once for the application lifetime."""
    global _configured
    if _configured:
        return

    # Filters
    context_filter = RequestContextFilter()
    sensitive_filter = SensitiveDataFilter()

    # Formatter
    if settings.is_production:
        formatter: logging.Formatter = JsonFormatter(
            app_name=settings.app_name,
            environment=settings.environment,
        )
    else:
        formatter = DevFormatter()

    # Handlers
    handlers: list[logging.Handler] = []

    if settings.is_production:
        if settings.log_output in ("stdout", "both"):
            handlers.append(logging.StreamHandler(sys.stdout))

        if settings.log_output in ("file", "both"):
            if settings.log_rotation:
                handlers.append(
                    logging.handlers.RotatingFileHandler(
                        settings.log_file_path,
                        maxBytes=settings.log_rotation_max_bytes,
                        backupCount=settings.log_rotation_backup_count,
                    )
                )
            else:
                handlers.append(logging.FileHandler(settings.log_file_path))
    else:
        handlers.append(logging.StreamHandler(sys.stdout))

    # Apply formatter and filters to each handler
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        handler.addFilter(sensitive_filter)

    # Root logger
    root = logging.getLogger()
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)

    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Force uvicorn to use our root handlers instead of its own
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        l = logging.getLogger(name)
        l.handlers.clear()
        l.propagate = True

    # Silence noisy third-party loggers
    for name in ("uvicorn.access", "sqlalchemy.engine", "httpx"):
        logging.getLogger(name).setLevel(logging.WARNING)

    _configured = True
