"""
tests/test_config.py — Tests for the production-safety config validator.
"""

import pytest

from app.config import Settings


def _base_kwargs(**overrides: str) -> dict[str, str]:
    kwargs = {
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/test",
        "environment": "production",
        "secret_key": "a-real-production-secret",
        "api_service_key": "a-real-production-service-key",
        "api_base_url": "http://fluent-api:9999",
    }
    kwargs.update(overrides)
    return kwargs


def test_production_settings_accepts_real_secrets():
    settings = Settings(**_base_kwargs())
    assert settings.environment == "production"


def test_production_settings_rejects_default_secret_key():
    with pytest.raises(ValueError, match="secret_key"):
        Settings(**_base_kwargs(secret_key="dev-secret-key-not-for-production"))


def test_production_settings_rejects_default_api_service_key():
    with pytest.raises(ValueError, match="api_service_key"):
        Settings(**_base_kwargs(api_service_key="dev-inbound-key-replace-me"))


def test_development_settings_allows_default_secrets():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:pass@localhost:5432/test",
        environment="development",
        api_base_url="http://fluent-api:9999",
        api_service_key="dev-inbound-key-replace-me",
    )
    assert settings.secret_key == "dev-secret-key-not-for-production"


def test_api_base_url_is_required():
    """Verify that api_base_url is a required field."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="api_base_url"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://user:pass@localhost:5432/test",
            environment="development",
            api_service_key="dev-inbound-key-replace-me",
        )
