"""Seed admin API keys.

Replaces the legacy `db/init/07-seed-admin-api-key.sh`. Idempotent — every
INSERT is guarded by ON CONFLICT (key_hash) DO NOTHING, so re-running this
on a populated database is a no-op.

Two rows may be seeded:

  * **Dev admin key** — only in non-production environments.
        Raw key:  ``fai_dev_admin``
        Hash:     sha256("fai_dev_admin")

  * **Production admin key** — only when ``Settings.admin_api_key_hash`` is
        set. The raw key is never stored or logged.
"""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging.utils import get_logger
from app.models.api_key import ApiKey

logger = get_logger(__name__)

# sha256("fai_dev_admin"). Safe to hard-code: the corresponding raw key is
# public and intended for local development only.
DEV_KEY_HASH = "6deee1cf62652696bb0d4393b3c30c813face041a13a5216dfe8718505df34f5"
DEV_KEY_NAME = "Dev Admin Key"
PROD_KEY_NAME = "Admin Key"

# Temporary placeholder owner for admin keys. The `ck_api_keys_single_owner`
# CHECK constraint requires every API key to be owned by exactly one user OR
# one org. Admin/platform keys do not yet have a real owner because the
# user/org schema work needed to designate "admin" users is being implemented
# elsewhere.
#
# Once that lands, the first few seeded users (and orgs) will be flagged as
# admins and this constant will be replaced by per-environment lookups.
# Until then, ID 97 is reserved as a placeholder admin user.
#
# TODO(fluent-platform): remove ADMIN_OWNER_USER_ID once seeded admin users
# exist and replace these inserts with a join against the admin user list.
ADMIN_OWNER_USER_ID = 97


async def _upsert_admin_key(session: AsyncSession, *, key_hash: str, name: str) -> bool:
    """Insert an admin key by hash; return True if a new row was created."""
    stmt = (
        pg_insert(ApiKey)
        .values(
            key_hash=key_hash,
            name=name,
            permissions=["admin"],
            is_active=True,
            owner_user_id=ADMIN_OWNER_USER_ID,
            owner_org_id=None,
        )
        .on_conflict_do_nothing(index_elements=["key_hash"])
    )
    result = await session.execute(stmt)
    return (result.rowcount or 0) > 0  # type: ignore[attr-defined]


async def seed_admin_api_keys(session: AsyncSession, settings: Settings) -> None:
    """Seed admin API key rows. Idempotent."""
    if not settings.is_production:
        created = await _upsert_admin_key(
            session, key_hash=DEV_KEY_HASH, name=DEV_KEY_NAME
        )
        logger.info(
            "Dev admin API key seed",
            created=created,
            raw_key_hint="fai_dev_admin",
            owner_user_id=ADMIN_OWNER_USER_ID,
        )

    if settings.admin_api_key_hash:
        created = await _upsert_admin_key(
            session,
            key_hash=settings.admin_api_key_hash,
            name=PROD_KEY_NAME,
        )
        logger.info(
            "Production admin API key seed",
            created=created,
            owner_user_id=ADMIN_OWNER_USER_ID,
        )
