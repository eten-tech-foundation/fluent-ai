"""
errors/ — Centralized error handling for the Fluent AI API.

Public surface re-exported here so consumers import from app.errors
rather than from internal sub-modules.
"""

from app.errors.codes import ErrorCode
from app.errors.exceptions import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    DatabaseException,
    ExternalServiceException,
    FluentAIException,
    NotFoundException,
    ValidationException,
)
from app.errors.schemas import ErrorDetail, ErrorResponse

__all__ = [
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "FluentAIException",
    "ValidationException",
    "AuthenticationException",
    "AuthorizationException",
    "NotFoundException",
    "ConflictException",
    "DatabaseException",
    "ExternalServiceException",
]
