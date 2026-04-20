"""
routers/projects.py — HTTP route handlers for the projects domain.

This layer only handles:
  - Request validation (via FastAPI + Pydantic)
  - Calling into crud/projects.py
  - Shaping the HTTP response

No DB queries or business logic live here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import projects as projects_crud
from app.database import get_db
from app.schemas.projects import ProjectListResponse, ProjectResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "/",
    response_model=ProjectListResponse,
    summary="List projects (AI read-only via role_ai_reader)",
)
async def list_projects(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ProjectListResponse:
    projects, total = await projects_crud.get_projects(db, limit=limit, offset=offset)
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in projects],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/_verify-permissions",
    summary="Verify ai_user SELECT-only access")
async def verify_permissions(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Dev/debug endpoint. Confirms:
      - ai_user can SELECT from public.projects
      - ai_user cannot INSERT into public.projects
    """
    results: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1 FROM public.projects LIMIT 1"))
        results["select_public_projects"] = "OK"
    except Exception as e:
        results["select_public_projects"] = f"FAILED: {e}"

    try:
        await db.execute(
            text(
                "INSERT INTO public.projects "
                "(name, source_language, target_language, organization, status, metadata) "
                "VALUES ('__test__', 0, 0, 0, 'not_assigned', '{}')"
            )
        )
        await db.rollback()
        results["insert_public_projects"] = "UNEXPECTED SUCCESS — check role grants"
    except Exception as e:
        await db.rollback()
        results["insert_public_projects"] = f"Correctly denied: {type(e).__name__}"

    return results


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get a project by ID (AI read-only)",
)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project = await projects_crud.get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    return ProjectResponse.model_validate(project)