# Standardize FastAPI Project Structure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the project directory layout with the standard FastAPI structure documented in `docs/architecture.md` by adding missing scaffold files (placeholders with comments only) and fixing broken items — without moving or rewriting any working code.

**Architecture:** Add placeholder files for every standard layer that is missing. Fix `__init__.py` gaps so all subdirectories are importable Python packages. Replace the fake-token logic in `dependencies.py` with real auth-connected dependencies. No working code is relocated.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy async, pydantic-settings, uv

---

## Gap Assessment

This table compares the standard structure (`docs/architecture.md`) to what currently exists.

| Standard path | Current path | Status |
|---|---|---|
| `app/main.py` | `app/main.py` | ✅ Good |
| `app/config.py` | `app/config.py` | ✅ Good |
| `app/dependencies.py` | `app/dependencies.py` | ⚠️ Contains stub token logic — doesn't use real auth |
| `app/api/v1/router.py` | — | ❌ Missing |
| `app/api/v1/endpoints/` | `app/routers/` | ⚠️ Wrong path, not versioned |
| `app/core/__init__.py` | — | ❌ Missing (dir exists, no `__init__.py`) |
| `app/core/security.py` | `app/security/auth.py` | ⚠️ Non-standard location |
| `app/core/exceptions.py` | — | ❌ Missing |
| `app/db/base.py` | `app/internal/models.py` (mixed) | ⚠️ `Base` embedded in models file |
| `app/db/session.py` | `app/database.py` | ⚠️ Non-standard filename/location |
| `app/db/migrations/` | — | ❌ Missing (no Alembic) |
| `app/models/` | `app/internal/models.py` | ⚠️ ORM models in non-standard location |
| `app/schemas/` | `app/schemas/` | ✅ Good |
| `app/services/` | `app/services/` | ✅ Good |
| `alembic.ini` | — | ❌ Missing |
| `tests/conftest.py` | — | ❌ Missing (no tests at all) |
| `tests/api/` | — | ❌ Missing |

**Additional issues found:**
- `app/core/config.py` — file exists but is empty (1 byte). `config.py` lives correctly in `app/config.py`.
- `app/internal/admin.py` — has a broken import (`from app.models.api_key import ApiKey`; that path doesn't exist). Not registered in `main.py`, so no runtime crash.
- `app/security/`, `app/services/`, `app/crud/`, `app/schemas/`, `app/core/` — all missing `__init__.py`, so they are not proper Python packages (works with uv/src layout but should be explicit).
- `app/routers/items.py` and `app/routers/users.py` — contain in-memory fake data and inline Pydantic schemas. These are placeholders already; this plan converts them to proper comment-only placeholders.

**What this plan does NOT do:**
- Does not move or rename any working file.
- Does not add Alembic (only adds `alembic.ini` as a comment-only placeholder).
- Does not add real tests (only adds placeholder `conftest.py` and test stubs).
- Does not change any route logic.

---

## File Map

Files created or modified by this plan:

**Created (placeholder, comment-only):**
- `src/app/api/__init__.py`
- `src/app/api/v1/__init__.py`
- `src/app/api/v1/router.py`
- `src/app/api/v1/endpoints/__init__.py`
- `src/app/core/__init__.py`
- `src/app/core/exceptions.py`
- `src/app/db/__init__.py`
- `src/app/db/base.py`
- `src/app/db/session.py`
- `src/app/db/migrations/.gitkeep`
- `src/app/models/__init__.py`
- `src/app/models/project.py`
- `src/app/models/api_key.py`
- `src/app/schemas/__init__.py`
- `src/app/services/__init__.py`
- `src/app/security/__init__.py`
- `src/app/crud/__init__.py`
- `alembic.ini`
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/api/__init__.py`
- `tests/api/v1/__init__.py`
- `tests/api/v1/test_projects.py`
- `tests/api/v1/test_api_keys.py`

**Modified:**
- `src/app/dependencies.py` — replace fake token stubs with real `get_db` re-export and auth dependency wrappers
- `src/app/core/config.py` — replace empty file with placeholder comment
- `src/app/internal/admin.py` — fix broken import so it doesn't blow up if ever imported

---

## Task 1: Add Missing `__init__.py` Files

Make every subdirectory a proper Python package.

**Files:**
- Create: `src/app/core/__init__.py`
- Create: `src/app/security/__init__.py`
- Create: `src/app/services/__init__.py`
- Create: `src/app/crud/__init__.py`
- Create: `src/app/schemas/__init__.py`

- [ ] **Step 1: Create the five `__init__.py` files**

`src/app/core/__init__.py`:
```python
# Core utilities: security, exceptions, shared config helpers.
# Import submodules explicitly when needed — do not star-import.
```

`src/app/security/__init__.py`:
```python
# Security layer: API key extraction, validation, permission guards.
# Primary module: auth.py
```

`src/app/services/__init__.py`:
```python
# Business logic layer.
# One module per domain (e.g. api_key.py).
# No FastAPI imports. No HTTP concepts. Pure Python.
```

`src/app/crud/__init__.py`:
```python
# Database query layer (read operations for read-only domains).
# Write operations live in services/ alongside their business logic.
```

`src/app/schemas/__init__.py`:
```python
# Pydantic request/response schemas.
# One module per domain. Never import ORM models here.
```

- [ ] **Step 2: Verify the app still starts**

```bash
cd /Users/kasey/code/github.com/eten-tech-foundation/fluent-ai
uv run uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8200 &
sleep 2
curl -s http://localhost:8200/ && kill %1
```
Expected: JSON response with `"message": "Welcome to Fluent AI API"`

- [ ] **Step 3: Commit**

```bash
git add src/app/core/__init__.py src/app/security/__init__.py src/app/services/__init__.py src/app/crud/__init__.py src/app/schemas/__init__.py
git commit -m "chore: add missing __init__.py to make subdirs proper packages"
```

---

## Task 2: Fix `app/core/config.py` and `app/internal/admin.py`

Replace the empty file and fix the broken import.

**Files:**
- Modify: `src/app/core/config.py`
- Modify: `src/app/internal/admin.py`

- [ ] **Step 1: Replace the empty `core/config.py` with a placeholder**

```python
# core/config.py — placeholder
#
# Standard location for app-wide configuration helpers that are shared
# across core/, db/, and services/ without creating circular imports.
#
# Currently, all settings live in app/config.py via pydantic-settings.
# Move Settings here if the config grows beyond what a single module can hold.
#
# Example contents when this file grows:
#   from pydantic_settings import BaseSettings
#   class Settings(BaseSettings): ...
#   @lru_cache
#   def get_settings() -> Settings: ...
```

- [ ] **Step 2: Fix the broken import in `internal/admin.py`**

The file imports `from app.models.api_key import ApiKey`, but that path doesn't exist. The correct path is `from app.internal.models import ApiKey`. The router is not registered in `main.py`, so this won't cause a runtime error today — but it will the moment anyone imports the file.

Replace the bad import:
```python
from fastapi import APIRouter, Depends

from app.internal.models import ApiKey
from app.security.auth import require_admin

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses={404: {"description": "Not found"}},
)


@router.get("/stats", dependencies=[Depends(require_admin)])
async def get_admin_stats():
    """Get administrative statistics"""
    return {
        "total_items": 2,
        "server_uptime": "2 days, 3 hours",
    }


@router.get("/health", dependencies=[Depends(require_admin)])
async def admin_health_check():
    """Admin health check with more details"""
    return {
        "status": "healthy",
        "database": "connected",
        "cache": "connected",
        "version": "0.1.0",
    }
```

- [ ] **Step 3: Verify the app still starts**

```bash
cd /Users/kasey/code/github.com/eten-tech-foundation/fluent-ai
uv run uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8200 &
sleep 2
curl -s http://localhost:8200/health && kill %1
```
Expected: `{"status":"healthy"}`

- [ ] **Step 4: Commit**

```bash
git add src/app/core/config.py src/app/internal/admin.py
git commit -m "fix: core/config.py placeholder, fix broken import in internal/admin.py"
```

---

## Task 3: Fix `app/dependencies.py`

Replace the stub fake-token functions with real dependencies that proxy into the actual auth layer.

**Files:**
- Modify: `src/app/dependencies.py`

- [ ] **Step 1: Replace the file contents**

The current file has two stub functions (`get_token_header`, `get_query_token`) that check for a hardcoded `"fake-super-secret-token"`. These are never used by any active router. Replace with real re-exports and a placeholder.

```python
# dependencies.py — shared FastAPI Depends() callables
#
# This is the single place where cross-cutting concerns are expressed as
# FastAPI dependencies. Routers import from here, not from security/ or db/
# directly, so swapping implementations only requires changing this file.
#
# Active dependencies (import and use these in routers):
#   - get_db         → yields an AsyncSession per request
#   - require_api_key → validates X-API-Key header, returns ApiKey record
#   - require_admin  → extends require_api_key, checks "admin" permission
#
# Example router usage:
#   from app.dependencies import get_db, require_api_key
#   @router.get("/")
#   async def list_items(db: AsyncSession = Depends(get_db), _=Depends(require_api_key)):
#       ...

from app.database import get_db  # noqa: F401 — re-exported for routers
from app.security.auth import require_admin, require_api_key  # noqa: F401

__all__ = ["get_db", "require_api_key", "require_admin"]
```

- [ ] **Step 2: Verify the app still starts**

```bash
cd /Users/kasey/code/github.com/eten-tech-foundation/fluent-ai
uv run uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8200 &
sleep 2
curl -s http://localhost:8200/ && kill %1
```
Expected: JSON welcome response

- [ ] **Step 3: Commit**

```bash
git add src/app/dependencies.py
git commit -m "chore: replace stub token logic in dependencies.py with real auth re-exports"
```

---

## Task 4: Add `app/api/` Versioned Endpoint Structure

Create the standard `api/v1/` scaffold. Existing `routers/` stays in place; this adds the correct future home for endpoints.

**Files:**
- Create: `src/app/api/__init__.py`
- Create: `src/app/api/v1/__init__.py`
- Create: `src/app/api/v1/router.py`
- Create: `src/app/api/v1/endpoints/__init__.py`

- [ ] **Step 1: Create `src/app/api/__init__.py`**

```python
# api/ — HTTP boundary layer.
#
# Organized by API version (v1/, v2/, ...) to allow the contract to evolve
# without breaking existing callers.
#
# Each version directory contains:
#   router.py      — aggregates all endpoint routers for that version
#   endpoints/     — one module per domain (projects.py, api_keys.py, ...)
#
# main.py imports only api/v1/router.py, staying ignorant of individual
# endpoint files.
#
# Current state: active endpoints live in app/routers/ (legacy location).
# Migrate them here one domain at a time as each is refactored.
```

- [ ] **Step 2: Create `src/app/api/v1/__init__.py`**

```python
# api/v1/ — Version 1 of the Fluent AI HTTP API.
```

- [ ] **Step 3: Create `src/app/api/v1/router.py`**

```python
# api/v1/router.py — aggregates all v1 endpoint routers.
#
# This is the only file main.py needs to import. It collects every endpoint
# module and includes their routers with the appropriate prefix/tags.
#
# When this file is active, main.py should look like:
#   from app.api.v1.router import router as api_v1_router
#   app.include_router(api_v1_router, prefix="/api/v1")
#
# Example contents when endpoints are migrated here:
#
#   from fastapi import APIRouter
#   from app.api.v1.endpoints import projects, api_keys
#
#   router = APIRouter()
#   router.include_router(projects.router, prefix="/projects", tags=["projects"])
#   router.include_router(api_keys.router, prefix="/api-keys", tags=["api-keys"])
```

- [ ] **Step 4: Create `src/app/api/v1/endpoints/__init__.py`**

```python
# api/v1/endpoints/ — one module per domain.
#
# Each module defines a single `router = APIRouter()` and attaches route
# handler functions to it. Handlers must:
#   1. Validate the request (FastAPI + Pydantic do this automatically).
#   2. Call exactly one service function.
#   3. Return a Pydantic schema instance.
#
# No DB queries. No business logic. No raw SQL.
#
# Current endpoint modules (to be migrated from app/routers/ over time):
#   projects.py   — list and retrieve projects (read-only, ai_user)
#   api_keys.py   — CRUD for API keys (admin-only writes)
#   users.py      — placeholder (no real implementation yet)
#   items.py      — placeholder (no real implementation yet)
```

- [ ] **Step 5: Verify the app still starts**

```bash
cd /Users/kasey/code/github.com/eten-tech-foundation/fluent-ai
uv run uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8200 &
sleep 2
curl -s http://localhost:8200/ && kill %1
```
Expected: JSON welcome response

- [ ] **Step 6: Commit**

```bash
git add src/app/api/
git commit -m "chore: add api/v1/ scaffold placeholders (standard versioned endpoint structure)"
```

---

## Task 5: Add `app/core/exceptions.py`

**Files:**
- Create: `src/app/core/exceptions.py`

- [ ] **Step 1: Create the placeholder**

```python
# core/exceptions.py — custom exception types and handlers.
#
# Define application-specific exceptions here and register handlers on the
# FastAPI app in main.py via app.add_exception_handler(...).
#
# Why this matters: centralizing exception handling prevents routers from
# raising bare HTTPException with inline status codes and messages scattered
# across the codebase. Instead, raise typed exceptions here; the handler
# converts them to the correct HTTP response.
#
# Example contents when this file is implemented:
#
#   from fastapi import Request
#   from fastapi.responses import JSONResponse
#
#   class NotFoundError(Exception):
#       def __init__(self, resource: str, id: int | str):
#           self.resource = resource
#           self.id = id
#
#   class PermissionDeniedError(Exception):
#       pass
#
#   async def not_found_handler(request: Request, exc: NotFoundError):
#       return JSONResponse(status_code=404, content={"detail": f"{exc.resource} {exc.id} not found"})
#
#   async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
#       return JSONResponse(status_code=403, content={"detail": "Permission denied"})
#
# Registration in main.py:
#   from app.core.exceptions import NotFoundError, not_found_handler
#   app.add_exception_handler(NotFoundError, not_found_handler)
```

- [ ] **Step 2: Commit**

```bash
git add src/app/core/exceptions.py
git commit -m "chore: add core/exceptions.py placeholder"
```

---

## Task 6: Add `app/db/` Structure

The engine and session currently live in `app/database.py`. The ORM `Base` is embedded in `app/internal/models.py`. This task adds the standard `db/` layer as placeholders pointing to those existing locations.

**Files:**
- Create: `src/app/db/__init__.py`
- Create: `src/app/db/base.py`
- Create: `src/app/db/session.py`
- Create: `src/app/db/migrations/.gitkeep`

- [ ] **Step 1: Create `src/app/db/__init__.py`**

```python
# db/ — database infrastructure layer.
#
# base.py    — SQLAlchemy DeclarativeBase shared by all ORM models
# session.py — async engine and session factory
# migrations/ — Alembic migration files (schema version control)
#
# Current state: engine/session live in app/database.py and Base lives in
# app/internal/models.py. Migrate to this structure when refactoring those files.
```

- [ ] **Step 2: Create `src/app/db/base.py`**

```python
# db/base.py — SQLAlchemy DeclarativeBase.
#
# All ORM models must inherit from Base defined here. Import every model
# module in this file so Alembic's autogenerate can detect them.
#
# Current state: Base is defined in app/internal/models.py alongside the
# model classes. Extract it here when splitting models into app/models/.
#
# Example contents when implemented:
#
#   from sqlalchemy.orm import DeclarativeBase
#
#   class Base(DeclarativeBase):
#       pass
#
#   # Import all models so Alembic sees them for autogenerate:
#   from app.models import project, api_key  # noqa: F401
```

- [ ] **Step 3: Create `src/app/db/session.py`**

```python
# db/session.py — async engine and session factory.
#
# Current state: this logic lives in app/database.py. Move it here when
# consolidating the db/ layer.
#
# Example contents when implemented:
#
#   from sqlalchemy.ext.asyncio import (
#       AsyncSession,
#       async_sessionmaker,
#       create_async_engine,
#   )
#   from app.config import get_settings
#
#   settings = get_settings()
#
#   engine = create_async_engine(
#       settings.async_database_url,
#       pool_size=settings.db_pool_size,
#       max_overflow=settings.db_max_overflow,
#       pool_timeout=settings.db_pool_timeout,
#       pool_recycle=settings.db_pool_recycle,
#       echo=settings.is_development,
#   )
#
#   AsyncSessionLocal = async_sessionmaker(
#       bind=engine,
#       class_=AsyncSession,
#       expire_on_commit=False,
#       autoflush=False,
#       autocommit=False,
#   )
#
#   async def get_db():
#       async with AsyncSessionLocal() as session:
#           try:
#               yield session
#               await session.commit()
#           except Exception:
#               await session.rollback()
#               raise
```

- [ ] **Step 4: Create `src/app/db/migrations/.gitkeep` and `alembic.ini`**

`src/app/db/migrations/.gitkeep`:
```
```
(empty file — keeps the directory tracked by git)

`alembic.ini` at project root:
```ini
# alembic.ini — placeholder
#
# Alembic is the standard migration tool for SQLAlchemy projects.
# It reads this file to find the migration scripts and database URL.
#
# To initialize Alembic for real:
#   uv add alembic
#   uv run alembic init src/app/db/migrations
#
# Then edit src/app/db/migrations/env.py to:
#   1. Import Base from app.db.base
#   2. Set target_metadata = Base.metadata
#   3. Load the database URL from app.config.get_settings().async_database_url
#
# Common commands:
#   uv run alembic revision --autogenerate -m "add users table"
#   uv run alembic upgrade head
#   uv run alembic downgrade -1
#   uv run alembic history
```

- [ ] **Step 5: Commit**

```bash
git add src/app/db/ alembic.ini
git commit -m "chore: add db/ scaffold placeholders and alembic.ini placeholder"
```

---

## Task 7: Add `app/models/` Structure

ORM models currently live in `app/internal/models.py`. Add the standard `models/` directory with comment-only placeholders.

**Files:**
- Create: `src/app/models/__init__.py`
- Create: `src/app/models/project.py`
- Create: `src/app/models/api_key.py`

- [ ] **Step 1: Create `src/app/models/__init__.py`**

```python
# models/ — SQLAlchemy ORM models.
#
# One file per domain object. Each model:
#   - Inherits from Base (to be defined in db/base.py)
#   - Maps to exactly one database table
#   - Contains no business logic
#   - Has no Pydantic imports
#
# Current state: ORM models live in app/internal/models.py.
# Migrate them here one at a time as each domain is refactored.
#
# Access rules for this service (ai_user):
#   public schema — SELECT only (role_ai_reader)
#   ai schema     — full DML (role_ai_data)
```

- [ ] **Step 2: Create `src/app/models/project.py`**

```python
# models/project.py — ORM model for public.projects.
#
# Current state: the Project model lives in app/internal/models.py.
# Move it here when consolidating the models/ layer.
#
# Access: SELECT only (ai_user has role_ai_reader on the public schema).
# Owner: fluent-server writes this table via web_user / role_web_data.
#
# Example contents when implemented:
#
#   from __future__ import annotations
#   from datetime import datetime
#   from typing import Any
#
#   from sqlalchemy import Boolean, DateTime, Integer, String, text
#   from sqlalchemy.dialects.postgresql import JSONB
#   from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
#
#   from app.db.base import Base
#
#   class Project(Base):
#       __tablename__ = "projects"
#       __table_args__ = {"schema": "public"}
#
#       id: Mapped[int] = mapped_column(Integer, primary_key=True)
#       name: Mapped[str] = mapped_column(String(255), nullable=False)
#       source_language: Mapped[int] = mapped_column(Integer, nullable=False)
#       target_language: Mapped[int] = mapped_column(Integer, nullable=False)
#       is_active: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))
#       created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
#       organization: Mapped[int] = mapped_column(Integer, nullable=False)
#       status: Mapped[str] = mapped_column(String, nullable=False)
#       metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
#       created_at: Mapped[datetime | None] = mapped_column(DateTime)
#       updated_at: Mapped[datetime | None] = mapped_column(DateTime)
```

- [ ] **Step 3: Create `src/app/models/api_key.py`**

```python
# models/api_key.py — ORM model for ai.api_keys.
#
# Current state: the ApiKey model lives in app/internal/models.py.
# Move it here when consolidating the models/ layer.
#
# Access: full DML (ai_user has role_ai_data on the ai schema).
# Owner: this service creates, updates, and revokes API keys.
#
# Example contents when implemented:
#
#   from __future__ import annotations
#   import uuid
#   from datetime import datetime
#
#   from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, String, Text, ARRAY
#   from sqlalchemy.dialects.postgresql import UUID
#
#   from app.db.base import Base
#
#   class ApiKey(Base):
#       __tablename__ = "api_keys"
#       __table_args__ = (
#           CheckConstraint(
#               "num_nonnulls(owner_user_id, owner_org_id) = 1",
#               name="ck_api_keys_single_owner",
#           ),
#           {"schema": "ai"},
#       )
#
#       id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
#       key_hash = Column(Text, nullable=False, unique=True)
#       name = Column(String(255), nullable=False)
#       permissions = Column(ARRAY(Text), nullable=False, server_default="{}")
#       is_active = Column(Boolean, nullable=False, default=True)
#       owner_user_id = Column(UUID(as_uuid=True), nullable=True)
#       owner_org_id = Column(UUID(as_uuid=True), nullable=True)
#       created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
#       expires_at = Column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Commit**

```bash
git add src/app/models/
git commit -m "chore: add models/ scaffold placeholders (standard ORM model location)"
```

---

## Task 8: Add `tests/` Scaffold

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/api/__init__.py`
- Create: `tests/api/v1/__init__.py`
- Create: `tests/api/v1/test_projects.py`
- Create: `tests/api/v1/test_api_keys.py`

- [ ] **Step 1: Create `tests/__init__.py`**

```python
# tests/ — test suite root.
#
# Mirror the app structure: tests/api/v1/ maps to app/api/v1/endpoints/.
# conftest.py provides shared fixtures for all tests.
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
# conftest.py — shared pytest fixtures.
#
# This file is auto-loaded by pytest before any test module.
# Define fixtures here that are needed across multiple test files.
#
# Key fixtures to implement:
#
#   @pytest.fixture
#   def client(app) -> TestClient:
#       # Synchronous test client for route-level tests.
#       # Use httpx.AsyncClient for async tests.
#       from fastapi.testclient import TestClient
#       return TestClient(app)
#
#   @pytest.fixture
#   async def db_session() -> AsyncGenerator[AsyncSession, None]:
#       # Override the get_db dependency with a test session that rolls back
#       # after each test so tests are isolated and don't pollute each other.
#       # Use app.dependency_overrides[get_db] = lambda: db_session
#       ...
#
#   @pytest.fixture
#   def admin_api_key(db_session) -> str:
#       # Create a seeded admin API key for tests that need auth.
#       # Return the raw key string (not the hash).
#       ...
#
# Required packages (add to pyproject.toml dev dependencies):
#   pytest
#   pytest-asyncio
#   httpx
```

- [ ] **Step 3: Create `tests/api/__init__.py` and `tests/api/v1/__init__.py`**

`tests/api/__init__.py`:
```python
# tests/api/ — HTTP layer tests.
```

`tests/api/v1/__init__.py`:
```python
# tests/api/v1/ — tests for v1 endpoints.
```

- [ ] **Step 4: Create `tests/api/v1/test_projects.py`**

```python
# tests/api/v1/test_projects.py — tests for the projects endpoints.
#
# Endpoints under test:
#   GET /projects/          list_projects — requires valid API key
#   GET /projects/{id}      get_project   — requires valid API key
#   GET /projects/_verify-permissions     — requires admin key
#
# Test cases to implement:
#
#   def test_list_projects_requires_auth(client):
#       response = client.get("/projects/")
#       assert response.status_code == 401
#
#   def test_list_projects_returns_paginated_list(client, valid_api_key, seeded_projects):
#       response = client.get("/projects/", headers={"X-API-Key": valid_api_key})
#       assert response.status_code == 200
#       body = response.json()
#       assert "items" in body
#       assert "total" in body
#
#   def test_get_project_not_found(client, valid_api_key):
#       response = client.get("/projects/999999", headers={"X-API-Key": valid_api_key})
#       assert response.status_code == 404
#
#   def test_get_project_returns_project(client, valid_api_key, seeded_project):
#       response = client.get(f"/projects/{seeded_project.id}", headers={"X-API-Key": valid_api_key})
#       assert response.status_code == 200
#       assert response.json()["id"] == seeded_project.id
```

- [ ] **Step 5: Create `tests/api/v1/test_api_keys.py`**

```python
# tests/api/v1/test_api_keys.py — tests for the API key management endpoints.
#
# Endpoints under test:
#   POST   /admin/api-keys         create_key  — admin only
#   GET    /admin/api-keys         list_keys   — admin only
#   PATCH  /admin/api-keys/{id}    patch_key   — admin only
#   DELETE /admin/api-keys/{id}    revoke_key  — admin only
#   GET    /api-keys/me            get_my_key  — any valid key
#
# Test cases to implement:
#
#   def test_create_key_requires_admin(client, non_admin_api_key):
#       response = client.post("/admin/api-keys", headers={"X-API-Key": non_admin_api_key}, json={...})
#       assert response.status_code == 403
#
#   def test_create_key_returns_raw_key_once(client, admin_api_key):
#       response = client.post("/admin/api-keys", headers={"X-API-Key": admin_api_key},
#           json={"name": "test-key", "permissions": []})
#       assert response.status_code == 201
#       body = response.json()
#       assert "raw_key" in body
#       assert body["raw_key"].startswith("fai_")
#
#   def test_revoke_key_makes_key_unusable(client, admin_api_key, db_session):
#       # Create a key, revoke it, then try to use it — expect 403.
#       ...
#
#   def test_get_my_key_returns_current_key_info(client, valid_api_key):
#       response = client.get("/api-keys/me", headers={"X-API-Key": valid_api_key})
#       assert response.status_code == 200
#       assert "raw_key" not in response.json()  # never exposed after creation
```

- [ ] **Step 6: Add test dependencies to `pyproject.toml`**

Add a `[dependency-groups]` section:
```toml
[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]
```

- [ ] **Step 7: Verify pytest can collect (even with no runnable tests yet)**

```bash
cd /Users/kasey/code/github.com/eten-tech-foundation/fluent-ai
uv run pytest tests/ --collect-only
```
Expected: pytest discovers test files and reports 0 tests collected (no errors).

- [ ] **Step 8: Commit**

```bash
git add tests/ pyproject.toml
git commit -m "chore: add tests/ scaffold with placeholder conftest and test stubs"
```

---

## Self-Review

**Spec coverage:**
- ✅ Architecture document written to `docs/architecture.md`
- ✅ Gap assessment documented in this plan
- ✅ `__init__.py` gaps covered (Task 1)
- ✅ Broken import in `internal/admin.py` fixed (Task 2)
- ✅ `dependencies.py` fake logic replaced (Task 3)
- ✅ `api/v1/` scaffold added (Task 4)
- ✅ `core/exceptions.py` placeholder added (Task 5)
- ✅ `db/` scaffold added with `alembic.ini` (Task 6)
- ✅ `models/` scaffold added (Task 7)
- ✅ `tests/` scaffold added (Task 8)

**Placeholder scan:** Every created file contains only comments. No `TBD` or `TODO` — all placeholders describe concrete example code and explain the current vs. target state.

**No working code is moved or deleted.** All active imports (`app.database`, `app.internal.models`, `app.security.auth`) remain valid after every task.
