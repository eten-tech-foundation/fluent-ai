"""
schemas/items.py — Pydantic schemas for the items domain.
"""

from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    """Request body for creating a new item."""

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Display name of the item.",
        examples=["Portal Gun"],
    )
    description: str | None = Field(
        default=None,
        max_length=500,
        description="Optional description of the item.",
        examples=["A gun that opens portals"],
    )


class ItemResponse(BaseModel):
    """Public item representation returned by the API."""

    item_id: str
    name: str
    description: str | None = None
