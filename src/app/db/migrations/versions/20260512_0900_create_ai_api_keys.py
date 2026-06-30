"""create ai.api_keys

Replaces the legacy `db/init/06-api-key.sql` bootstrap script. This is the
first Alembic revision for the `ai` schema; the `alembic_version` table
will be created in the `ai` schema by env.py on first apply.

Revision ID: 20260512_0900
Revises:
Create Date: 2026-05-12 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260512_0900"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("owner_org_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        sa.CheckConstraint(
            "num_nonnulls(owner_user_id, owner_org_id) = 1",
            name="ck_api_keys_single_owner",
        ),
        schema="ai",
    )

    # Hot-path lookup: validate an incoming key by hash. Partial index
    # keeps the structure small by skipping revoked keys.
    op.create_index(
        "idx_api_keys_key_hash",
        "api_keys",
        ["key_hash"],
        schema="ai",
        postgresql_where=sa.text("is_active = true"),
    )

    # Belt-and-suspenders: the ALTER DEFAULT PRIVILEGES in scripts/bootstrap.py
    # already grant ai_user on tables created in `ai` by role_migrations,
    # but issuing an explicit GRANT here makes the migration self-contained
    # and tolerant of environments without those default privileges.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ai.api_keys TO ai_user")


def downgrade() -> None:
    op.drop_index("idx_api_keys_key_hash", table_name="api_keys", schema="ai")
    op.drop_table("api_keys", schema="ai")
