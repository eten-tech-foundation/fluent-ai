"""models/ — SQLAlchemy ORM models owned by this service.

All models here inherit from OwnedBase (app.db.base), map to tables in the
`ai` schema, and are managed by Alembic migrations.

There are no external/borrowed models: API data is fetched over HTTP.
"""

from app.models.api_key import ApiKey

__all__ = ["ApiKey"]
