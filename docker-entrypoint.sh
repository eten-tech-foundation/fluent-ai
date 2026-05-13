#!/usr/bin/env sh
set -e

# Alembic and seeds are idempotent — safe to run on every container start.
# Skip with SKIP_DB_BOOTSTRAP=1 (e.g. for one-off shells or local debugging).
if [ "${SKIP_DB_BOOTSTRAP:-0}" != "1" ]; then
  echo ">>> Applying ai-schema migrations (alembic upgrade head)..."
  uv run alembic upgrade head

  echo ">>> Running ai-schema seeds..."
  PYTHONPATH=/app/src uv run python -m app.db.seeds
fi

exec uv run fastapi dev src/app/main.py --host 0.0.0.0 --port 8200
