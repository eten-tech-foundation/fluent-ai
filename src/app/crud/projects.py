"""
crud/projects.py — Database query logic for the projects domain.

All queries run as ai_user, which has SELECT-only access on public schema
via role_ai_reader. No write operations are defined here intentionally.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.internal.models import Project


async def get_projects(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Project], int]:
    """
    Fetch a paginated list of projects and the total count.

    Returns a tuple of (projects, total) so the router can
    build a paginated response without a second query round-trip.
    """
    count_result = await db.execute(select(func.count()).select_from(Project))
    total = count_result.scalar_one()

    result = await db.execute(
        select(Project)
        .order_by(Project.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    projects = list(result.scalars().all())

    return projects, total


async def get_project_by_id(
    db: AsyncSession,
    project_id: int,
) -> Project | None:
    """Fetch a single project by primary key. Returns None if not found."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    return result.scalar_one_or_none()