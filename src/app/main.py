"""
main.py — FastAPI application factory for the Fluent AI service.
"""
from fastapi import FastAPI

from app.api.v1.router import router as api_v1_router
from app.config import get_settings
from app.errors.handlers import register_exception_handlers
from app.errors.schemas import ErrorResponse
from app.middleware.request_id import RequestIDMiddleware
from app.routers import projects

settings = get_settings()

# --------------------------------------------------------------------------- #
# Error response OpenAPI examples shared across all routers
# --------------------------------------------------------------------------- #
_ERROR_RESPONSES: dict = {
    400: {"model": ErrorResponse, "description": "Bad request / validation error"},
    401: {"model": ErrorResponse, "description": "Authentication required"},
    403: {"model": ErrorResponse, "description": "Insufficient permissions"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "Resource conflict"},
    422: {"model": ErrorResponse, "description": "Request validation failed"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
    502: {"model": ErrorResponse, "description": "External service error"},
}

app = FastAPI(
    title=settings.app_name,
    description="AI Services for the Fluent Ecosystem",
    version=settings.app_version,
    debug=settings.debug,
    responses=_ERROR_RESPONSES,
)

# --------------------------------------------------------------------------- #
# Middleware — registered before handlers so request_id is always present
# --------------------------------------------------------------------------- #
app.add_middleware(RequestIDMiddleware)

# --------------------------------------------------------------------------- #
# Exception handlers
# --------------------------------------------------------------------------- #
register_exception_handlers(app)

# --------------------------------------------------------------------------- #
# Routers
# --------------------------------------------------------------------------- #
app.include_router(projects.router, tags=["projects"])
app.include_router(api_v1_router)

# GET /docs provides interactive API documentation
# GET /redoc provides alternative interactive API documentation
# GET /openapi.json provides OpenAPI schema

@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.app_version,
        "environment": settings.environment,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
