"""db/base.py — SQLAlchemy DeclarativeBase subclasses.

Two bases are defined because this service shares a PostgreSQL database with
fluent-platform and must never run migrations against schemas it does not own.

    OwnedBase    — parent for models in the `ai` schema (api_keys, ...).
                   Alembic's target_metadata = OwnedBase.metadata.
                   All `ai`-schema model modules must be imported below so
                   Alembic's autogenerate sees them.

    ExternalBase — parent for read-only models borrowed from other schemas
                   (e.g. public.projects, owned by fluent-platform).
                   Never included in Alembic metadata. No DML allowed.
"""

from sqlalchemy.orm import DeclarativeBase


class OwnedBase(DeclarativeBase):
    """Base for models in the `ai` schema. Alembic manages these."""


class ExternalBase(DeclarativeBase):
    """Base for read-only models borrowed from external schemas."""


# Import owned-schema models so Alembic autogenerate can detect them.
# Do NOT import ExternalBase models here — Alembic must never see them.
from app.models import api_key  # noqa: E402, F401
