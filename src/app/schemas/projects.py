"""
schemas/projects.py — Pydantic DTOs for the projects domain.

These are the shapes the API accepts and returns.
Kept separate from the SQLAlchemy ORM model in internal/models.py.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    source_language: int
    target_language: int
    is_active: bool | None = True
    created_by: int | None = None
    organization: int
    status: str
    metadata: dict[str, Any] = Field(alias="metadata_")
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectListResponse(BaseModel):
    """Wrapper for paginated project lists."""

    items: list[ProjectResponse]
    total: int
    limit: int
    offset: int