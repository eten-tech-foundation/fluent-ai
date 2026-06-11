#!/usr/bin/env sh
set -e

# bootstrap → migrations → seeds are idempotent — safe on every container start.
# Skip all three with SKIP_DB_BOOTSTRAP=1 (e.g. for one-off shells or debugging).
if [ "${SKIP_DB_BOOTSTRAP:-0}" != "1" ]; then
  echo ">>> Bootstrapping ai schema/roles..."
  PYTHONPATH=/app/src uv run python scripts/bootstrap.py

  echo ">>> Applying ai-schema migrations (alembic upgrade head)..."
  uv run alembic upgrade head

  echo ">>> Running ai-schema seeds..."
  PYTHONPATH=/app/src uv run python -m app.db.seeds
fi

exec uv run fastapi dev src/app/main.py --host 0.0.0.0 --port 8200
