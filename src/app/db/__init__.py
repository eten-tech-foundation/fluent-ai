# db/ — database infrastructure layer.
#
# base.py    — SQLAlchemy DeclarativeBase subclasses (OwnedBase, ExternalBase)
# session.py — async engine and session factory
# migrations/ — Alembic migration files (schema version control)
#
# Architectural rule: this service owns the ai schema and reads the public schema.
#   OwnedBase  → ai schema models → Alembic manages these
#   ExternalBase → public schema models → Alembic never touches these
#
# Current state: engine/session live in app/database.py (working).
# Migrate to db/session.py when consolidating the db/ layer.
