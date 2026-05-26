"""db/seeds/ — idempotent seed runners for the `ai` schema.

Seeds are applied after Alembic migrations on every container start (see
`docker-entrypoint.sh`). Each seed must:

  * Be idempotent — safe to run on every startup.
  * Only touch tables owned by this service (schema `ai`).
  * Read configuration from `app.config.Settings`, never from os.environ.
"""

from app.db.seeds.api_keys import seed_admin_api_keys
from app.db.seeds.runner import run_all_seeds

__all__ = ["run_all_seeds", "seed_admin_api_keys"]
