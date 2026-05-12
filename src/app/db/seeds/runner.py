"""Top-level seed runner.

Opens a single AsyncSession, executes every seed in order inside one
transaction, and commits. Idempotency is each individual seed's
responsibility.
"""

from __future__ import annotations

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.db.seeds.api_keys import seed_admin_api_keys
from app.logging.utils import get_logger

logger = get_logger(__name__)


async def run_all_seeds() -> None:
    """Run every seed in order. Safe to invoke on every container start."""
    settings = get_settings()
    logger.info("Running database seeds", environment=settings.environment)

    async with AsyncSessionLocal() as session:
        try:
            await seed_admin_api_keys(session, settings)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    logger.info("Database seeds complete")
