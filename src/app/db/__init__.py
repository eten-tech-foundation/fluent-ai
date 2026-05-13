"""db/ — database infrastructure layer.

base.py       — OwnedBase / ExternalBase DeclarativeBase subclasses.
session.py    — re-exports the async engine and session factory from
                app.database (kept there for now to avoid churn).
migrations/   — Alembic migration files (only OwnedBase models).
seeds/        — Idempotent Python seed runner.

Architectural rule: this service owns the `ai` schema and reads `public`.
    OwnedBase    → ai schema models → Alembic manages these.
    ExternalBase → public schema models → Alembic never touches these.
"""
