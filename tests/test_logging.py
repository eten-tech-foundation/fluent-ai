"""
tests/test_logging.py — Tests for the structured logging subsystem.

Covers:
  - Production safety: show_stack_traces is forced off in production
  - Logging configuration: correct handlers/formatters for dev vs prod
  - Sensitive data redaction
  - Structured logger keyword forwarding
"""

import json
import logging
import os
from typing import Any
from unittest.mock import patch

from app.config import Settings
from app.logging.config import configure_logging
from app.logging.filters import SensitiveDataFilter, scrub_dict, scrub_url
from app.logging.formatters import DevFormatter, JsonFormatter
from app.logging.utils import StructuredLogger, get_logger


def _settings(environment: str, **kwargs: Any) -> Settings:
    """Build a Settings instance suitable for unit tests."""
    defaults: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "api_base_url": "http://localhost:8000",
        "api_service_key": "test-service-key",
        "secret_key": "not-the-insecure-default-secret",
    }
    return Settings(environment=environment, **{**defaults, **kwargs})


# --------------------------------------------------------------------------- #
# Production safety — show_stack_traces must NEVER be True in production
# --------------------------------------------------------------------------- #


class TestProductionSafety:
    """Ensure stack traces cannot leak in production."""

    def test_stack_traces_forced_off_in_production(self):
        """Even if SHOW_STACK_TRACES=true, production must override to False."""
        settings = _settings(
            environment="production",
            show_stack_traces=True,
        )
        assert settings.show_stack_traces is False

    def test_stack_traces_default_off_in_production(self):
        """Default value of show_stack_traces is False in production."""
        settings = _settings(environment="production")
        assert settings.show_stack_traces is False

    def test_stack_traces_allowed_in_development(self):
        """Development environments may enable stack traces."""
        settings = _settings(
            environment="development",
            show_stack_traces=True,
        )
        assert settings.show_stack_traces is True

    def test_stack_traces_off_by_default_in_development(self):
        """Even in development, show_stack_traces defaults to False."""
        settings = _settings(environment="development")
        assert settings.show_stack_traces is False

    def test_stack_traces_via_env_var_blocked_in_production(self):
        """Verify env var SHOW_STACK_TRACES=true is overridden in production."""
        env = {
            "ENVIRONMENT": "production",
            "SHOW_STACK_TRACES": "true",
            "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = _settings(
                _env_file=None,
                environment="production",
                show_stack_traces=True,
            )
            assert settings.show_stack_traces is False

    def test_is_production_property(self):
        """Verify is_production returns True only for 'production'."""
        prod = _settings(environment="production")
        dev = _settings(environment="development")
        assert prod.is_production is True
        assert dev.is_production is False


# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #


class TestConfigureLogging:
    """Test configure_logging sets up handlers correctly."""

    def setup_method(self):
        """Reset the _configured flag before each test."""
        import app.logging.config as cfg

        cfg._configured = False

    def teardown_method(self):
        """Clean up root logger handlers after each test."""
        root = logging.getLogger()
        root.handlers.clear()

    def test_dev_uses_dev_formatter(self):
        """Development mode should use DevFormatter with stdout handler."""
        settings = _settings(environment="development")
        configure_logging(settings)

        root = logging.getLogger()
        assert len(root.handlers) >= 1
        assert isinstance(root.handlers[0].formatter, DevFormatter)

    def test_prod_uses_json_formatter(self):
        """Production mode should use JsonFormatter."""
        import app.logging.config as cfg

        cfg._configured = False
        settings = _settings(
            environment="production",
            log_output="stdout",
        )
        configure_logging(settings)

        root = logging.getLogger()
        assert len(root.handlers) >= 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_idempotent_configuration(self):
        """configure_logging should only run once."""
        settings = _settings(environment="development")
        configure_logging(settings)
        handler_count = len(logging.getLogger().handlers)
        configure_logging(settings)
        assert len(logging.getLogger().handlers) == handler_count


# --------------------------------------------------------------------------- #
# Sensitive data redaction
# --------------------------------------------------------------------------- #


class TestSensitiveDataRedaction:
    """Test that sensitive fields are properly scrubbed."""

    def test_scrub_dict_redacts_password(self):
        data = {"username": "alice", "password": "s3cret"}
        result = scrub_dict(data)
        assert result["username"] == "alice"
        assert result["password"] == "[REDACTED]"

    def test_scrub_dict_redacts_api_key(self):
        data = {"api_key": "sk-abc123", "endpoint": "/v1/chat"}
        result = scrub_dict(data)
        assert result["api_key"] == "[REDACTED]"
        assert result["endpoint"] == "/v1/chat"

    def test_scrub_dict_redacts_nested(self):
        data = {"auth": {"token": "tok_123", "user": "bob"}}
        result = scrub_dict(data)
        assert result["auth"]["token"] == "[REDACTED]"
        assert result["auth"]["user"] == "bob"

    def test_scrub_dict_redacts_in_list(self):
        data = {"users": [{"name": "alice", "secret": "x"}]}
        result = scrub_dict(data)
        assert result["users"][0]["secret"] == "[REDACTED]"
        assert result["users"][0]["name"] == "alice"

    def test_scrub_url_redacts_token_param(self):
        url = "https://api.example.com/data?token=abc123&page=1"
        result = scrub_url(url)
        assert "abc123" not in result
        assert "page=1" in result
        # urlencode encodes brackets: [REDACTED] → %5BREDACTED%5D
        assert "REDACTED" in result

    def test_scrub_url_preserves_safe_params(self):
        url = "https://api.example.com/data?page=1&limit=10"
        result = scrub_url(url)
        assert result == url

    def test_sensitive_data_filter_scrubs_record(self):
        """SensitiveDataFilter should scrub _structured dict on a log record."""
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        record._structured = {"user": "alice", "password": "s3cret"}

        f = SensitiveDataFilter()
        f.filter(record)

        assert record._structured["user"] == "alice"
        assert record._structured["password"] == "[REDACTED]"


# --------------------------------------------------------------------------- #
# Structured logger
# --------------------------------------------------------------------------- #


class TestStructuredLogger:
    """Test StructuredLogger forwards keyword arguments correctly."""

    def test_get_logger_returns_structured_logger(self):
        log = get_logger("test.module")
        assert isinstance(log, StructuredLogger)

    def test_kwargs_stored_in_structured(self):
        """Keyword arguments should land in record._structured."""
        log = get_logger("test.structured")
        # Use a handler that captures records
        records: list[logging.LogRecord] = []

        class Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        log.logger.addHandler(Capture())
        log.logger.setLevel(logging.DEBUG)

        log.info("hello", user_id="u123", action="login")

        assert len(records) == 1
        structured = getattr(records[0], "_structured", {})
        assert structured["user_id"] == "u123"
        assert structured["action"] == "login"

        # Cleanup
        log.logger.handlers.clear()


# --------------------------------------------------------------------------- #
# Formatters
# --------------------------------------------------------------------------- #


class TestJsonFormatter:
    """Test JsonFormatter output structure."""

    def test_produces_valid_json(self):
        formatter = JsonFormatter(app_name="TestApp", environment="test")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-123"
        record.correlation_id = ""

        output = formatter.format(record)
        data = json.loads(output)

        assert data["message"] == "hello world"
        assert data["level"] == "INFO"
        assert data["app_name"] == "TestApp"
        assert data["request_id"] == "req-123"

    def test_includes_exception_info(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="error",
                args=(),
                exc_info=sys.exc_info(),
            )

        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]
