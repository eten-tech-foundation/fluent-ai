# Integrating Greek-Room into Fluent-AI

## Overview

This guide provides a complete, step-by-step implementation for wrapping Greek-Room's Bible translation checks into your Fluent-AI FastAPI service using the **Adapter Pattern**.

### Key Design Principles

- **No Database Coupling**: Greek-Room checks are stateless functions. Use only Fluent-AI's existing auth and API key infrastructure.
- **Clean Separation**: Wrap Greek-Room functionality in a service layer that your routers call.
- **Easy Extensibility**: Structure supports adding more Greek-Room tools (script analysis, other `owl` checks) in the future.
- **API Key Authentication**: Leverage your existing `X-API-Key` header validation.

---

## Step 1: Add Greek-Room Dependency

Update your `pyproject.toml` to include the greekroom package:

```toml
[project]
name = "fluent-ai"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
    "fastapi[standard]>=0.128.0",
    "pydantic-settings>=2.0.0",
    # Database
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.30.0",
    "alembic>=1.13.0",
    # AI
    "google-genai>=1.73.1",
    # Bible Translation Tools
    "greekroom @ git+https://github.com/BibleNLP/greek-room.git@main",
]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
    "ruff>=0.4.0",
    "mypy>=1.10.0",
]
Then install:

bash
uv sync
Step 2: Create Pydantic Schemas
Create src/app/schemas/greek_room.py:

Python
"""
Pydantic schemas for Greek-Room Bible translation checks.
"""
from typing import Any

from pydantic import BaseModel, Field


class VerseText(BaseModel):
    """A single scripture verse with its text."""

    snt_id: str = Field(
        ...,
        description="Scripture reference (e.g., 'GEN 1:1', 'JHN 12:24')",
    )
    text: str = Field(..., description="The verse text to analyze")


class RepeatedWordsCheckRequest(BaseModel):
    """Request to check for repeated words in Bible translation text."""

    lang_code: str = Field(
        ...,
        description="ISO 639-3 language code (e.g., 'eng' for English)",
    )
    lang_name: str = Field(..., description="Human-readable language name (e.g., 'English')")
    project_id: str = Field(
        ...,
        description="Project identifier for tracking (e.g., 'eng-sample')",
    )
    project_name: str = Field(
        ...,
        description="Full name of the Bible translation project",
    )
    verses: list[VerseText] = Field(
        ...,
        description="List of verses to check for repeated words",
    )


class RepeatedWordsCheckResult(BaseModel):
    """Result of a repeated words check."""

    message_id: str = Field(
        ...,
        description="Unique identifier for this check run",
    )
    result: dict[str, Any] = Field(
        ...,
        description="MCP-formatted result dictionary containing the analysis",
    )
    metadata: dict[str, Any] = Field(
        ...,
        description="Additional metadata about the check execution",
    )
Step 3: Create the Greek-Room Service Layer
Create src/app/services/greek_room_service.py:

Python
"""
Service layer for Greek-Room Bible translation checks.

This module wraps greek-room functions and manages lifecycle concerns
like data file loading. The check functions are pure and stateless;
the service just organizes them.
"""
import json
import logging
import uuid
from typing import Any

from greekroom.owl import repeated_words

logger = logging.getLogger(__name__)


class GreekRoomService:
    """
    Manages Bible translation checks via Greek-Room tools.

    Data files are loaded once at service initialization for efficiency.
    """

    def __init__(self):
        """Initialize the service by loading Greek-Room data files."""
        logger.info("Initializing GreekRoomService")
        try:
            self._data_filename_dict = repeated_words.load_data_filename()
            logger.info("Greek-Room data files loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Greek-Room data files: {e}")
            raise

    async def check_repeated_words(
        self,
        lang_code: str,
        lang_name: str,
        project_id: str,
        project_name: str,
        check_corpus: list[dict[str, str]],
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Check for repeated words in Bible translation text.

        Identifies patterns like "the the" or "truly truly" that may indicate
        translation errors or legitimate linguistic patterns (tracked in
        greek-room's legitimate_duplicates.jsonl).

        Args:
            lang_code: ISO 639-3 language code (e.g., 'eng')
            lang_name: Human-readable language name (e.g., 'English')
            project_id: Project identifier for tracking (e.g., 'eng-sample')
            project_name: Full project name (e.g., 'English Bible')
            check_corpus: List of {"snt-id": "GEN 1:1", "text": "..."} dicts
            message_id: Optional message ID (auto-generated if not provided)

        Returns:
            Dictionary with keys:
                - message_id: Unique identifier for this check
                - result: MCP-formatted result dict with analysis
                - metadata: Additional execution metadata

        Raises:
            Exception: If check execution fails
        """
        if not message_id:
            message_id = f"{lang_code}-{uuid.uuid4().hex[:8]}"

        logger.debug(
            "Starting repeated_words check",
            message_id=message_id,
            lang_code=lang_code,
            project_id=project_id,
            verse_count=len(check_corpus),
        )

        # Build MCP 2.0 JSON-RPC request
        task_d = {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "BibleTranslationCheck",
            "params": [
                {
                    "lang-code": lang_code,
                    "lang-name": lang_name,
                    "project-id": project_id,
                    "project-name": project_name,
                    "selectors": [
                        {
                            "tool": "GreekRoom",
                            "checks": ["RepeatedWords"],
                        }
                    ],
                    "check-corpus": check_corpus,
                }
            ],
        }

        task_s = json.dumps(task_d)
        corpus = repeated_words.new_corpus(message_id)

        try:
            # Execute the check
            mcp_d, misc_data_dict, check_corpus_list = repeated_words.check_mcp(
                task_s, self._data_filename_dict, corpus
            )

            logger.debug(
                "Repeated_words check completed",
                message_id=message_id,
                result_keys=list(mcp_d.keys()) if mcp_d else [],
            )

            return {
                "message_id": message_id,
                "result": mcp_d,
                "metadata": misc_data_dict or {},
            }

        except Exception as e:
            logger.error(
                f"Repeated_words check failed: {e}",
                message_id=message_id,
                lang_code=lang_code,
            )
            raise
Step 4: Create the Greek-Room Router
Create src/app/routers/greek_room.py:

Python
"""
API routes for Greek-Room Bible translation checks.

Exposes Greek-Room tools (repeated words checks, etc.) via REST endpoints.
All endpoints require API key authentication via X-API-Key header.
"""
import logging
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import require_api_key
from app.schemas.greek_room import (
    RepeatedWordsCheckRequest,
    RepeatedWordsCheckResult,
)
from app.services.greek_room_service import GreekRoomService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools/greek-room", tags=["bible-translation-tools"])

# Initialize the service once at module load time
greek_room_service = GreekRoomService()


@router.post(
    "/repeated-words",
    response_model=RepeatedWordsCheckResult,
    status_code=HTTPStatus.OK,
    summary="Check for repeated words in Bible translation",
    description=(
        "Identifies repeated words (e.g., 'the the', 'truly truly') in Bible "
        "translation text that may indicate translation errors or are tracked as "
        "legitimate repeated patterns (e.g., 'amen amen' in Greek). "
        "Results follow the MCP (Manifest Canonical Protocol) format."
    ),
    responses={
        HTTPStatus.OK: {
            "description": "Check completed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "message_id": "eng-a1b2c3d4",
                        "result": {
                            "jsonrpc": "2.0",
                            "id": "eng-a1b2c3d4",
                            "result": {
                                "issues": [
                                    {
                                        "snt-id": "GEN 1:1",
                                        "issue-type": "RepeatedWords",
                                        "issue-comment": "repeated word: in",
                                    }
                                ]
                            },
                        },
                        "metadata": {},
                    }
                }
            },
        },
        HTTPStatus.UNAUTHORIZED: {"description": "Missing or invalid API key"},
        HTTPStatus.UNPROCESSABLE_ENTITY: {"description": "Request validation failed"},
        HTTPStatus.INTERNAL_SERVER_ERROR: {"description": "Check execution failed"},
    },
)
async def check_repeated_words(
    request: RepeatedWordsCheckRequest,
    _=Depends(require_api_key),
) -> RepeatedWordsCheckResult:
    """
    Check for repeated words in Bible translation verses.

    Requires authentication via X-API-Key header.
    """
    try:
        logger.info(
            "Processing repeated_words check request",
            lang_code=request.lang_code,
            project_id=request.project_id,
            verse_count=len(request.verses),
        )

        # Convert verses to greek-room format
        check_corpus = [
            {"snt-id": v.snt_id, "text": v.text} for v in request.verses
        ]

        # Execute check via service
        result = await greek_room_service.check_repeated_words(
            lang_code=request.lang_code,
            lang_name=request.lang_name,
            project_id=request.project_id,
            project_name=request.project_name,
            check_corpus=check_corpus,
        )

        logger.info(
            "Repeated_words check completed successfully",
            message_id=result["message_id"],
            lang_code=request.lang_code,
        )

        return RepeatedWordsCheckResult(**result)

    except Exception as e:
        logger.error(
            f"Repeated_words check endpoint error: {e}",
            lang_code=request.lang_code,
            project_id=request.project_id,
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Check execution failed. Please try again.",
        )
Step 5: Register the Router in Your Main App
Update src/app/main.py to include the Greek-Room router:

Python
"""
main.py — FastAPI application factory for the Fluent AI service.
"""

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
from app.routers import projects, greek_room  # ADD THIS LINE
from app.internal import admin


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
    logger.info(
        "Application started",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        log_output=settings.log_output,
        log_file=settings.log_file_path,
    )
    yield
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
app.include_router(projects.router, tags=["projects"])
app.include_router(admin.router)
app.include_router(api_v1_router)
app.include_router(greek_room.router)  # ADD THIS LINE


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
Step 6: Test the Integration
Start the Service
bash
./fai.sh up
Test the Endpoint
bash
curl -X POST http://localhost:8200/tools/greek-room/repeated-words \
  -H "X-API-Key: your_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "lang_code": "eng",
    "lang_name": "English",
    "project_id": "eng-sample",
    "project_name": "English Bible",
    "verses": [
      {
        "snt_id": "GEN 1:1",
        "text": "In in the beginning God created the heavens and the earth."
      },
      {
        "snt_id": "JHN 12:24",
        "text": "Truly truly, I say to you, unless a grain of wheat falls into the earth and dies..."
      }
    ]
  }'
Expected Response
JSON
{
  "message_id": "eng-a1b2c3d4",
  "result": {
    "jsonrpc": "2.0",
    "id": "eng-a1b2c3d4",
    "result": {
      "issues": [
        {
          "snt-id": "GEN 1:1",
          "issue-type": "RepeatedWords",
          "issue-comment": "repeated word: in"
        }
      ]
    }
  },
  "metadata": {}
}
Future Extensibility: Adding More Greek-Room Tools
Adding a Script Analysis Check
When you want to add more Greek-Room tools (e.g., script direction analysis), follow this pattern:

1. Add to GreekRoomService (src/app/services/greek_room_service.py):

Python
class GreekRoomService:
    # ... existing __init__ and check_repeated_words ...

    async def check_script_analysis(
        self,
        lang_code: str,
        lang_name: str,
        project_name: str,
        check_corpus: list[dict[str, str]],
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Check script direction, quotation marks, etc."""
        # Similar implementation pattern
        pass
2. Add schemas to src/app/schemas/greek_room.py:

Python
class ScriptAnalysisRequest(BaseModel):
    lang_code: str
    lang_name: str
    # ... other fields

class ScriptAnalysisResult(BaseModel):
    message_id: str
    result: dict[str, Any]
    metadata: dict[str, Any]
3. Add route to src/app/routers/greek_room.py:

Python
@router.post(
    "/script-analysis",
    response_model=ScriptAnalysisResult,
    # ... docstring and responses ...
)
async def check_script_analysis(
    request: ScriptAnalysisRequest,
    _=Depends(require_api_key),
) -> ScriptAnalysisResult:
    # Similar implementation
    pass
Optional: Tool Registry Pattern
If you plan many tools, consider a tool registry for DRY code:

Python
# src/app/services/greek_room_service.py

GREEK_ROOM_TOOLS = {
    "repeated_words": {
        "method": "check_repeated_words",
        "schema": RepeatedWordsCheckRequest,
    },
    "script_analysis": {
        "method": "check_script_analysis",
        "schema": ScriptAnalysisRequest,
    },
}

# Generic endpoint
@router.post("/check/{tool_name}")
async def generic_check(tool_name: str, request: dict, _=Depends(require_api_key)):
    if tool_name not in GREEK_ROOM_TOOLS:
        raise HTTPException(404, f"Tool '{tool_name}' not found")

    tool_info = GREEK_ROOM_TOOLS[tool_name]
    method = getattr(greek_room_service, tool_info["method"])
    return await method(**request)
Architecture Diagram
Code
Fluent-AI (Your Service)
│
├─ API Layer
│  └─ routers/greek_room.py
│     └─ POST /tools/greek-room/repeated-words
│        └─ Validates X-API-Key via require_api_key()
│           └─ Converts request to internal format
│              └─ Calls service
│
├─ Service Layer
│  └─ services/greek_room_service.py
│     └─ GreekRoomService.check_repeated_words()
│        └─ Wraps greekroom.owl.repeated_words.check_mcp()
│           └─ Pure, stateless function call
│
├─ Schema Layer
│  └─ schemas/greek_room.py
│     └─ RepeatedWordsCheckRequest (input validation)
│     └─ RepeatedWordsCheckResult (output serialization)
│
└─ Existing Fluent-AI Infrastructure
   ├─ Authentication: X-API-Key header → require_api_key()
   ├─ Database: Your existing PostgreSQL (not used for checks)
   └─ Config: Pydantic settings
Key Takeaways
✅ No Database Coupling: Greek-Room checks are pure functions. Your API key auth is sufficient.

✅ Stateless Design: The GreekRoomService loads data files once and exposes stateless methods.

✅ Clean Extensibility: Adding new Greek-Room tools requires minimal code—just add service method, schema, and route.

✅ Your Auth Works: Leverage your existing X-API-Key authentication for all tool endpoints.

✅ Optional Usage Tracking: Implement tool usage tracking at a higher abstraction layer in Fluent-AI (separate from tool implementation).

✅ Future-Proof: This pattern scales to Fluent-AI's whole tool collection without tight coupling.

Troubleshooting
"ModuleNotFoundError: No module named 'greekroom'"
Ensure the dependency was added and installed:

bash
uv sync
uv run python -c "import greekroom; print(greekroom.__file__)"
"Greek-Room data files not found"
Greek-Room looks for legitimate_duplicates.jsonl in standard directories. Ensure the package is properly installed and the data files are present. Check the Greek-Room documentation for data file locations.

Repeated Words Check Returns Empty Results
This is expected if the text doesn't contain any repeated words. The MCP result will have an empty issues array.

Performance: Slow First Request
The first request loads Greek-Room's data files (one-time cost). Subsequent requests are faster.

Next Steps
✅ Add the dependency to pyproject.toml and run uv sync
✅ Create the four new files (schemas, service, router, plus update main.py)
✅ Test with a sample request
✅ Implement usage tracking later in a centralized Fluent-AI audit layer
✅ Add more Greek-Room tools by following the extensibility pattern