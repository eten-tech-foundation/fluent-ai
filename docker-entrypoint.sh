#!/usr/bin/env sh
set -e

if [ ! -f /tmp/.db-initialized ]; then
  echo "First run detected — running migrations and seeds..."
  # TODO: Add migration command when ai schema migrations are set up
  # e.g.: uv run alembic upgrade head
  # TODO: Add seed command when ai seeds are created
  # e.g.: uv run python src/db/seeds/seed.py
  touch /tmp/.db-initialized
  echo "Database initialized."
fi

exec uv run fastapi dev src/app/main.py --host 0.0.0.0 --port 8200
