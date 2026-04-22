# db/base.py — SQLAlchemy DeclarativeBase subclasses.
#
# TWO bases are defined here because this service shares a PostgreSQL database
# with fluent-server and must never run migrations against schemas it does not own.
#
#   OwnedBase   — parent for models in the ai schema (api_keys, etc.)
#                 Alembic target_metadata = OwnedBase.metadata
#                 Import all ai-schema models here for Alembic autogenerate.
#
#   ExternalBase — parent for read-only models borrowed from other schemas
#                  (public.projects, etc., owned by fluent-server).
#                  Never included in Alembic metadata.
#                  No INSERT/UPDATE/DELETE on models inheriting from this.
#
# Current state: a single Base class is defined in app/internal/models.py
# alongside the model classes. Extract both bases here when splitting models
# into app/models/ (owned) and app/internal/ (external/read-only).
#
# Example contents when implemented:
#
#   from sqlalchemy.orm import DeclarativeBase
#
#   class OwnedBase(DeclarativeBase):
#       """Base for models in the ai schema. Alembic manages these."""
#       pass
#
#   class ExternalBase(DeclarativeBase):
#       """Base for read-only models borrowed from external schemas."""
#       pass
#
#   # Import all ai-schema models so Alembic autogenerate can detect them:
#   from app.models import api_key  # noqa: F401
#
#   # Do NOT import external models here — Alembic must never see them.
