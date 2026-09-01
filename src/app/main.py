"""
main.py — FastAPI application factory for the Fluent AI service.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import router as api_v1_router
from app.config import get_settings
from app.errors.handlers import register_exception_handlers
from app.errors.schemas import ErrorResponse
from app.logging import configure_logging
from app.logging.middleware import LoggingMiddleware
from app.logging.utils import get_logger
from app.middleware.request_id import RequestIDMiddleware
from app.routers import admin
from app.services.greek_room.repeated_words import RepeatedWordsService
from app.worker.suggestion_processor import worker_loop


settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)
logger.info(
    "Application initialising",
    app_name=settings.app_name,
    version=settings.app_version,
    environment=settings.environment,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Instantiate AI tool services once at startup so heavy initialisation
    # (data file loading, client connection setup) happens before the
    # first request arrives, and any missing-resource errors surface in
    # the boot logs rather than as a mysterious 500 to the first caller.
    app.state.repeated_words_service = RepeatedWordsService()

    logger.info(
        "Application started",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        log_output=settings.log_output,
        log_file=settings.log_file_path,
    )

    worker_task: asyncio.Task | None = None
    if settings.enable_suggestion_worker:
        worker_task = asyncio.create_task(worker_loop())
        logger.info("AI suggestion worker started")
    else:
        logger.info("AI suggestion worker disabled")

    yield

    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    logger.info("Application shutting down")


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
    lifespan=lifespan,
)

# --------------------------------------------------------------------------- #
# Middleware — registered before handlers so request_id is always present
# --------------------------------------------------------------------------- #
# Order matters: last-added = outermost = runs first.
# RequestIDMiddleware must be outermost so it assigns request_id before
# LoggingMiddleware reads it.
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIDMiddleware)

# --------------------------------------------------------------------------- #
# Exception handlers
# --------------------------------------------------------------------------- #
register_exception_handlers(app)

# --------------------------------------------------------------------------- #
# Routers
# --------------------------------------------------------------------------- #
app.include_router(admin.router)
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
    # The deploy workflows poll this endpoint to decide whether a rollout
    # succeeded, and the deployment runbooks read `commit` off it to confirm
    # which build is live. Keep `status` first and unchanged.
    return {
        "status": "healthy",
        "version": settings.app_version,
        "environment": settings.environment,
        "commit": settings.app_commit_sha,
    }
