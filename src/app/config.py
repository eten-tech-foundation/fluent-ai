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
    
    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://user:password@localhost/fluent_ai"
    )
    
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


@lru_cache
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()
