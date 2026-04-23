"""
errors/schemas.py — Pydantic models for the structured error response envelope.

Wire format:

    {
      "error": {
        "code":       "RESOURCE_NOT_FOUND",
        "message":    "Project 99 not found",
        "details":    {"project_id": 99},
        "timestamp":  "2024-01-01T12:00:00Z",
        "request_id": "a1b2c3d4-..."
      }
    }

These models are referenced in router response declarations so that OpenAPI
documents the error shape correctly.
"""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Inner error object — the structured payload inside the error envelope."""

    code: str = Field(
        description="Machine-readable error code constant.",
        examples=["RESOURCE_NOT_FOUND"],
    )
    message: str = Field(
        description="Human-readable description safe for external consumption.",
        examples=["Project 99 not found"],
    )
    details: Any | None = Field(
        default=None,
        description=(
            "Optional structured context: field names, constraint details, etc. "
            "Omitted when null."
        ),
    )
    timestamp: str = Field(
        description="ISO-8601 UTC timestamp of when the error occurred.",
        examples=["2024-01-01T12:00:00Z"],
    )
    request_id: str = Field(
        description="Unique ID for this request — include in bug reports.",
        examples=["reqid_1a2b3c4d5e6f7g8h9i0j"],
    )


class ErrorResponse(BaseModel):
    """Top-level error envelope returned on all non-2xx responses."""

    error: ErrorDetail


def build_error_response(
    *,
    code: str,
    message: str,
    request_id: str,
    details: Any | None = None,
) -> dict:
    """
    Build the raw dict payload for a JSONResponse.

    Using a plain dict (rather than model_dump()) avoids double-serialisation
    of the datetime string inside JSONResponse.
    """
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "request_id": request_id,
        }
    }
