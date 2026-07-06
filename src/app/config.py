import os
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_env_file() -> str:
    """Get the environment-specific .env file path."""
    env = os.getenv("ENVIRONMENT", "development")
    if env == "production":
        return ".env.prod"
    # Try .env.dev first, fall back to .env
    if os.path.exists(".env.dev"):
        return ".env.dev"
    return ".env"


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=(".env", _get_env_file()),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="Fluent AI API")
    app_version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    environment: str = Field(default="development")

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8200)

    # Database — ai_user connects as: read public, write ai
    # Use postgresql+asyncpg:// scheme for async SQLAlchemy
    # Example: postgresql+asyncpg://ai_user:pa$$word@db:5432/fluent
    # Database
    database_url: str = Field(
        description="Full asyncpg connection URL. Set in .env — never hardcode here."
    )

    # Optional override used only by Alembic — connect as the `migrations`
    # role (DDL privileges) instead of `ai_user` (DML only). Falls back to
    # database_url when unset.
    migrations_database_url: str | None = Field(default=None)

    # Connection pool settings
    db_pool_size: int = Field(default=5)  # number of persistent connections
    db_max_overflow: int = Field(default=10)  # extra connections above pool_size
    db_pool_timeout: int = Field(default=30)  # seconds to wait for a connection
    db_pool_recycle: int = Field(default=1800)  # recycle connections after 30 min

    # Security
    secret_key: str = Field(default="your-secret-key-change-in-production")

    # API Keys
    api_key_default_expiry_days: int | None = Field(
        default=None,
        description=(
            "Default expiry in days applied when creating a new API key "
            "and no explicit expires_at is provided. None = never expires."
        ),
    )
    admin_api_key_hash: str | None = Field(
        default=None,
        description=(
            "SHA-256 hash of the seed admin API key. "
            "Set in .env — never put the raw key here."
        ),
    )

    # Error handling
    # Set show_stack_traces=True in .env to include tracebacks in dev.
    # Never enable in production — enforced by _enforce_production_safety below.
    show_stack_traces: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    _INSECURE_SECRET_KEY_DEFAULT = "your-secret-key-change-in-production"
    _INSECURE_API_SERVICE_KEY_DEFAULT = "dev-inbound-key-replace-me"

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """Force show_stack_traces off in production, and refuse to boot
        with known placeholder secrets in production."""
        if self.environment == "production" and self.show_stack_traces:
            self.show_stack_traces = False

        if self.environment == "production":
            if self.secret_key == self._INSECURE_SECRET_KEY_DEFAULT:
                raise ValueError(
                    "secret_key is still set to its insecure development "
                    "default — set a real SECRET_KEY in production."
                )
            if self.api_service_key == self._INSECURE_API_SERVICE_KEY_DEFAULT:
                raise ValueError(
                    "api_service_key is still set to its insecure development "
                    "default — set a real API_SERVICE_KEY in production."
                )

        return self

    log_output: str = Field(
        default="stdout",
        description="Log destination: 'stdout', 'file', or 'both'.",
    )
    log_file_path: str = Field(
        default="/app/logs/app.log",
        description="Path for file log output. Used when log_output is 'file' or 'both'.",
    )
    log_rotation: bool = Field(
        default=True,
        description="Enable RotatingFileHandler. No effect when log_output is 'stdout'.",
    )
    log_rotation_max_bytes: int = Field(
        default=10_485_760,
        description="Max log file size in bytes before rotation (default 10 MB).",
    )
    log_rotation_backup_count: int = Field(
        default=5,
        description="Number of rotated backup files to retain.",
    )
    log_sampling_rate: float = Field(
        default=1.0,
        description=(
            "Fraction of INFO-level request logs to emit (0.0–1.0). "
            "1.0 = log everything. Reduce for high-throughput endpoints."
        ),
    )

    # AI Suggestion Worker
    enable_suggestion_worker: bool = Field(
        default=True,
        description="Enable the background AI suggestion worker loop.",
    )

    # External AI Services
    openai_api_key: str | None = Field(default=None)
    anthropic_api_key: str | None = Field(default=None)
    google_ai_api_key: str | None = Field(default=None)
    google_ai_model: str = Field(default="gemini-2.5-flash-lite")

    # Internal API Integration
    api_base_url: str = Field(default="http://fluent-api:9999")
    api_service_key: str = Field(default="dev-inbound-key-replace-me")

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"

    @property
    def async_database_url(self) -> str:
        """
        Ensure the database URL uses the asyncpg driver.

        Handles the case where DATABASE_URL is set with a plain
        postgres:// or postgresql:// scheme (e.g. from .env).
        """
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def alembic_database_url(self) -> str:
        """URL used by Alembic. Prefer migrations_database_url, else fall back."""
        url = self.migrations_database_url or self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()  # type: ignore[call-arg]
