"""db/ — database infrastructure layer.

base.py       — OwnedBase DeclarativeBase subclass.
session.py    — re-exports the async engine and session factory from
                app.database (kept there for now to avoid churn).
migrations/   — Alembic migration files (only OwnedBase models).
seeds/        — Idempotent Python seed runner.

Architectural rule: this service owns the `ai` schema only.
    OwnedBase → ai schema models → Alembic manages these.
    API data is fetched over HTTP; there are no external/borrowed ORM models.
"""
