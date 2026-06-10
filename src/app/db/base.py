"""db/base.py — SQLAlchemy DeclarativeBase subclasses.

    OwnedBase — parent for all models in the `ai` schema (api_keys, ...).
                Alembic's target_metadata = OwnedBase.metadata.
                All `ai`-schema model modules must be imported below so
                Alembic's autogenerate sees them.

There are no external/borrowed models: the AI service fetches API data over
HTTP and has no SQL access to any other schema.
"""

from sqlalchemy.orm import DeclarativeBase


class OwnedBase(DeclarativeBase):
    """Base for models in the `ai` schema. Alembic manages these."""


# Import owned-schema models so Alembic autogenerate can detect them.
from app.models import api_key  # noqa: E402, F401
