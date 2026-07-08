"""add_jobs_status_check_constraint

Revision ID: 6a563c230130
Revises: 20260629_1355_create_jobs
Create Date: 2026-07-07 17:58:27.931254+00:00

"""

from collections.abc import Sequence

from alembic import op

revision: str = "6a563c230130"
down_revision: str | Sequence[str] | None = "20260629_1355_create_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_jobs_status_valid",
        "jobs",
        "status IN ('queued', 'processing', 'completed', 'failed')",
        schema="ai",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_status_valid", "jobs", schema="ai", type_="check")
