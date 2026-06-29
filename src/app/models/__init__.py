"""models/ — SQLAlchemy ORM models owned by this service.

All models here inherit from OwnedBase (app.db.base), map to tables in the
`ai` schema, and are managed by Alembic migrations.

Models for tables this service does NOT own live under app/internal/ and
inherit from ExternalBase instead.
"""

from app.models.api_key import ApiKey
from app.models.job import Job

__all__ = ["ApiKey", "Job"]
