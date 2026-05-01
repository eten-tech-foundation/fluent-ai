# models/ — ORM models owned by this service.
#
# All models here:
#   - Inherit from OwnedBase (defined in db/base.py)
#   - Map to tables in the ai schema
#   - Are managed by Alembic migrations
#   - May be read and written by this service
#
# One file per domain object.
#
# Current state: the ApiKey model lives in app/internal/models.py alongside
# read-only external models. Migrate it here when splitting internal/models.py.
#
# Rule: if a model belongs to a table this service does NOT own, it must NOT
# live here — put it in app/internal/ instead.
