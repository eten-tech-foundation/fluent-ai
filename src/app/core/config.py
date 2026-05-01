# core/config.py — placeholder
#
# Standard location for app-wide configuration helpers shared across
# core/, db/, and services/ without creating circular imports.
#
# Currently, all settings live in app/config.py via pydantic-settings.
# Move Settings here if the config grows beyond what a single module can hold.
#
# Example contents when this file grows:
#   from pydantic_settings import BaseSettings
#   class Settings(BaseSettings): ...
#   @lru_cache
#   def get_settings() -> Settings: ...
