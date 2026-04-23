"""
schemas/users.py — Pydantic schemas for the users domain.
"""

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Request body for creating a new user."""

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Alphanumeric username (3–50 chars, underscores and hyphens allowed).",
        examples=["jane_doe"],
    )
    email: EmailStr = Field(
        description="Valid email address.",
        examples=["jane@example.com"],
    )
    full_name: str | None = Field(
        default=None,
        max_length=120,
        description="Optional display name.",
        examples=["Jane Doe"],
    )
    disabled: bool | None = Field(
        default=False,
        description="Whether the account is disabled.",
    )


class User(BaseModel):
    """Public user representation returned by the API."""

    username: str
    email: str
    full_name: str | None = None
    disabled: bool | None = False


class UserInDB(User):
    """Internal user record with hashed password (never returned to callers)."""

    hashed_password: str
