"""
crud/projects.py — Database query logic for the projects domain.

All queries run as ai_user, which has SELECT-only access on public schema
via role_ai_reader. No write operations are defined here intentionally.

SQLAlchemy errors are caught and re-raised as DatabaseException so the
global exception handler can produce a clean, structured error response
without leaking internal database details to callers.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError, TimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors.codes import ErrorCode
from app.errors.exceptions import DatabaseException
from app.errors.utils import with_db_retry
from app.internal.models import Project


@with_db_retry()
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

    Raises:
        DatabaseException: If the underlying query fails for any reason.
    """
    try:
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

    except TimeoutError as exc:
        raise DatabaseException(
            message="Database query timed out.",
            code=ErrorCode.DATABASE_TIMEOUT,
            details={"operation": "get_projects"},
        ) from exc
    except IntegrityError as exc:
        raise DatabaseException(
            message="Database constraint violation.",
            code=ErrorCode.DATABASE_CONSTRAINT_VIOLATION,
            details={"operation": "get_projects"},
        ) from exc
    except OperationalError as exc:
        raise DatabaseException(
            message="Failed to connect to the database.",
            code=ErrorCode.DATABASE_CONNECTION_ERROR,
            details={"operation": "get_projects"},
        ) from exc
    except SQLAlchemyError as exc:
        raise DatabaseException(
            message="Failed to retrieve projects.",
            code=ErrorCode.DATABASE_ERROR,
            details={"operation": "get_projects"},
        ) from exc


@with_db_retry()
async def get_project_by_id(
    db: AsyncSession,
    project_id: int,
) -> Project | None:
    """
    Fetch a single project by primary key. Returns None if not found.

    Raises:
        DatabaseException: If the underlying query fails for any reason.
    """
    try:
        result = await db.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    except TimeoutError as exc:
        raise DatabaseException(
            message="Database query timed out.",
            code=ErrorCode.DATABASE_TIMEOUT,
            details={"operation": "get_project_by_id", "project_id": project_id},
        ) from exc
    except IntegrityError as exc:
        raise DatabaseException(
            message="Database constraint violation.",
            code=ErrorCode.DATABASE_CONSTRAINT_VIOLATION,
            details={"operation": "get_project_by_id", "project_id": project_id},
        ) from exc
    except OperationalError as exc:
        raise DatabaseException(
            message="Failed to connect to the database.",
            code=ErrorCode.DATABASE_CONNECTION_ERROR,
            details={"operation": "get_project_by_id", "project_id": project_id},
        ) from exc
    except SQLAlchemyError as exc:
        raise DatabaseException(
            message="Failed to retrieve project.",
            code=ErrorCode.DATABASE_ERROR,
            details={"operation": "get_project_by_id", "project_id": project_id},
        ) from exc
