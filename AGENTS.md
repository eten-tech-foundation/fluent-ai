# AGENTS.md — Fluent AI

## Project Overview

Python 3.14 FastAPI backend for AI services powering the Fluent Ecosystem. Managed with
`uv` (Astral), containerized with Docker/Podman. Currently in early scaffold/PoC phase
with placeholder in-memory data (no real database yet).

## Build & Run Commands

```bash
# Install dependencies (local, outside Docker)
uv sync

# Run dev server locally (hot-reload)
uv run fastapi dev src/app/main.py --host 0.0.0.0 --port 8200

# Run production server locally
uv run fastapi run src/app/main.py --host 0.0.0.0 --port 8200

# Docker dev mode (preferred workflow)
./fai start                  # dev with cloud DB
./fai --local-db start       # dev with local PostgreSQL
./fai stop
./fai restart
./fai logs
./fai shell                  # shell into running container

# Docker production
./fai --prod start
```

## Testing

**No test infrastructure exists yet.** When adding tests:

- Use `pytest` as the test framework (`.pytest_cache/` is in `.gitignore`)
- Add `pytest` and `httpx` to dev dependencies in `pyproject.toml`
- Place tests in `src/tests/` (structure shown in README)
- Use FastAPI's `TestClient` (from `httpx`) for endpoint testing
- Run all tests: `uv run pytest`
- Run a single test file: `uv run pytest src/tests/test_users.py`
- Run a single test: `uv run pytest src/tests/test_users.py::test_read_user -v`
- Run with coverage: `uv run pytest --cov=app`

## Linting & Formatting

**No linters or formatters are configured yet.** The `.gitignore` includes entries for
`.ruff_cache/`, `.black_cache/`, and `.isort.cfg`, indicating ruff is the intended tool.
When adding linting:

- Use `ruff` for both linting and formatting (replaces black, isort, flake8)
- Configure in `pyproject.toml` under `[tool.ruff]`
- Run: `uv run ruff check .` and `uv run ruff format .`

## Project Structure

```
src/app/                      # All Python source code
├── __init__.py               # Empty package marker
├── main.py                   # FastAPI app creation, root routes, router mounting
├── config.py                 # Pydantic BaseSettings + cached getter
├── dependencies.py           # Shared FastAPI dependency functions
├── core/                     # Reserved for future shared utilities (empty)
├── routers/                  # Public route handlers, one file per domain entity
│   ├── items.py
│   └── users.py
└── internal/                 # Internal/admin routes
    └── admin.py
```

Key config files at project root: `pyproject.toml`, `uv.lock`, `Dockerfile`,
`Dockerfile.dev`, `docker-compose.{base,dev,prod}.yml`, `.env.*.example`, `fai`/`fai.bat`.

## Code Style Guidelines

### Imports

- Use `from X import Y` style (named imports). Avoid bare `import X` except for stdlib
  modules like `os`.
- Never use wildcard imports (`from X import *`).
- Use absolute imports anchored at `app.` (e.g., `from app.config import get_settings`).
  Do not use relative imports.
- Order import groups with blank-line separators:
  1. Standard library (`os`, `functools`, `typing`)
  2. Third-party (`fastapi`, `pydantic`, `pydantic_settings`)
  3. Local application (`app.config`, `app.routers`, `app.dependencies`)

### Type Annotations

- Use modern Python 3.10+ union syntax: `str | None` (not `Optional[str]`).
- Use built-in generic types: `list[dict]`, `dict[str, User]` (not `List`, `Dict` from
  `typing`). This project targets Python 3.14.
- Use Pydantic `BaseModel` for request/response data schemas.
- Use Pydantic `BaseSettings` for configuration classes.
- Annotate return types on utility/config functions. Route handlers may omit return type
  annotations and use `response_model=` on the decorator instead.

### Naming Conventions

- **Files:** lowercase snake_case (`items.py`, `dependencies.py`). Single words preferred.
- **Classes:** PascalCase (`Settings`, `User`, `UserInDB`).
- **Functions/methods:** snake_case (`get_settings`, `read_items`, `create_user`).
- **Route handlers:** `verb_noun` pattern — `read_` for GET, `create_` for POST.
- **Variables:** snake_case (`fake_items_db`, `item_id`).
- **Private functions:** leading underscore (`_get_env_file`).
- **Router variable:** always named `router` in each router module.
- **Packages/directories:** lowercase, single word (`routers/`, `internal/`, `core/`).

### FastAPI Patterns

- Each router file follows this structure:
  1. Imports
  2. `router = APIRouter(prefix=..., tags=..., responses=...)` instantiation
  3. Pydantic models (if any)
  4. Data/state (if any)
  5. Route handler functions (`async def`)
- All route handlers must be `async def`.
- Use `response_model=` on route decorators for typed responses.
- Use FastAPI's `Depends()` for dependency injection. Shared dependencies go in
  `dependencies.py`. Router-specific dependencies can be passed to `APIRouter(dependencies=[...])`.
- Mount routers in `main.py` via `app.include_router(module.router, prefix=..., tags=...)`.

### Error Handling

- Use `fastapi.HTTPException` for all error responses.
- Use guard-clause style: check error condition, raise immediately.
- Use named status constants: `status.HTTP_404_NOT_FOUND`, `status.HTTP_400_BAD_REQUEST`
  (not bare integers like `404`).
- Pattern:
  ```python
  if resource is None:
      raise HTTPException(
          status_code=status.HTTP_404_NOT_FOUND,
          detail="Resource not found",
      )
  ```

### Configuration

- All app settings live in `src/app/config.py` as a `Settings(BaseSettings)` class.
- Access settings via the cached `get_settings()` function, never by constructing
  `Settings()` directly.
- Environment variables are loaded from `.env.dev` or `.env.prod` based on the
  `ENVIRONMENT` env var.
- Secrets and API keys must never be committed. Use `.env.*.example` files as templates.

### Formatting

- 4-space indentation (Python standard).
- Trailing commas on multi-line structures (function args, dicts, lists).
- Docstrings: triple-quoted, single-line for simple descriptions.
  ```python
  def get_settings() -> Settings:
      """Get application settings (cached)."""
  ```
- Minimal inline comments; use them for section labels, not obvious code explanation.
- Blank line between import groups. Two blank lines before top-level definitions.

### Dependencies & Packaging

- `uv` is the package manager. Always use `uv sync`, `uv add`, `uv run`.
- Lock file (`uv.lock`) must be committed and kept up to date.
- Python version: `>=3.14` (specified in `pyproject.toml` and `.python-version`).
- Add runtime deps to `[project] dependencies` in `pyproject.toml`.
- Dev dependencies should go in `[dependency-groups]` when added.

## Environment Setup

```bash
# Copy the appropriate env template
cp .env.dev.example .env.dev    # development
cp .env.prod.example .env.prod  # production

# Key env vars: APP_NAME, APP_VERSION, DEBUG, ENVIRONMENT, HOST, PORT,
# DATABASE_URL, SECRET_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY
```

## Docker Architecture

- `docker-compose.base.yml` — shared config (port 8200, env vars)
- `docker-compose.dev.yml` — dev overlay (hot-reload, source volume mount)
- `docker-compose.prod.yml` — production overlay (resource limits, health check)
- `Dockerfile` — production multi-stage build
- `Dockerfile.dev` — development build (source mounted as volume)
- Use `--profile local-db` (via `./fai --local-db`) to include a local PostgreSQL.
