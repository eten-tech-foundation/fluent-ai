import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_env_file() -> str:
    """Determine which .env file to load based on ENVIRONMENT variable."""
    env = os.getenv("ENVIRONMENT", "development")
    if env == "production":
        return ".env.prod"
    return ".env.dev"


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    model_config = SettingsConfigDict(
        env_file=_get_env_file(),
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

    # Connection pool settings
    db_pool_size: int = Field(default=5)       # number of persistent connections
    db_max_overflow: int = Field(default=10)   # extra connections above pool_size
    db_pool_timeout: int = Field(default=30)   # seconds to wait for a connection
    db_pool_recycle: int = Field(default=1800) # recycle connections after 30 min

    # Security
    secret_key: str = Field(
        default="your-secret-key-change-in-production"
    )
    
    # External AI Services
    openai_api_key: str | None = Field(default=None)
    anthropic_api_key: str | None = Field(default=None)
    
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
        postgres:// or postgresql:// scheme (e.g. from .env.dev).
        """
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()
