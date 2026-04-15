# AGENTS.md — Fluent AI

## Project Overview

Python 3.14 FastAPI backend for AI services powering the Fluent Ecosystem. Managed with
`uv` (Astral), containerized with Docker Compose (Docker) or native Podman pods (Podman).

## Operating Modes

There are three ways to run the service:

| Mode | Command | DB port | When to use |
|---|---|---|---|
| **Standalone** | `./fai.sh up` | 5433 | Working on this service only |
| **Service-only** | `./fai.sh up ai` | — (external) | Platform's DB already running |
| **Ecosystem** | `./fluent.sh up` (in fluent-platform) | 5432 | Full integration work |

Set `DATABASE_URL` in `.env` to point at the platform DB (`localhost:5432`) when running
in service-only mode alongside `fluent.sh`.

## Build & Run Commands

```bash
# Container workflow (preferred)
./fai.sh setup          # Create .env from .env.example
./fai.sh up             # Start DB (port 5433) + AI service (port 8200)
./fai.sh up db          # Start only the database
./fai.sh up ai          # Start only the AI service
./fai.sh down           # Stop and remove all services
./fai.sh down ai        # Stop only the AI service
./fai.sh restart        # Restart all services
./fai.sh restart ai     # Restart only the AI service
./fai.sh logs           # Tail all logs
./fai.sh logs ai        # Tail AI service logs
./fai.sh logs db        # Tail database logs
./fai.sh status         # Show container/pod status (all states)
./fai.sh shell          # Shell into AI container
./fai.sh shell db       # Open psql session

# Development commands (run inside AI container)
./fai.sh test           # Run pytest
./fai.sh lint           # ruff check
./fai.sh lint:fix       # ruff check --fix
./fai.sh format         # ruff format
./fai.sh format:check   # ruff format --check
./fai.sh typecheck      # mypy src
./fai.sh run <cmd>      # uv run <cmd>

# Database
./fai.sh db:psql        # Open psql session
./fai.sh db:migrate     # Run migrations (TODO)
./fai.sh db:seed        # Run seeds (TODO)

# Lifecycle
./fai.sh build          # Rebuild AI image without cache
./fai.sh clean          # Remove containers and volumes
./fai.sh fresh          # Remove containers, volumes, and image

# Local development (outside container)
uv sync
uv run fastapi dev src/app/main.py --host 0.0.0.0 --port 8200
```

Windows users: use `fai.ps1` with the same commands.

## Testing

Use `pytest` as the test framework:

```bash
./fai.sh test                                    # All tests
./fai.sh run pytest src/tests/test_users.py      # Single file
./fai.sh run pytest src/tests/test_users.py::test_read_user -v
./fai.sh run pytest --cov=app                    # With coverage
```

Add `pytest` and `httpx` to dev dependencies in `pyproject.toml` when writing tests.
Place tests in `src/tests/`. Use FastAPI's `TestClient` (from `httpx`) for endpoint testing.

## Linting & Formatting

Uses `ruff` for both linting and formatting. Configure under `[tool.ruff]` in `pyproject.toml`.

```bash
./fai.sh lint           # Check
./fai.sh lint:fix       # Auto-fix
./fai.sh format         # Format
./fai.sh format:check   # Dry-run check
```

## Project Structure

```
src/app/                      # All Python source code
├── __init__.py               # Empty package marker
├── main.py                   # FastAPI app creation, root routes, router mounting
├── config.py                 # Pydantic BaseSettings + cached getter
├── core/
│   └── config.py             # Core configuration
├── dependencies.py           # Shared FastAPI dependency functions
├── routers/                  # Public route handlers, one file per domain entity
│   ├── __init__.py
│   ├── items.py
│   └── users.py
└── internal/                 # Internal/admin routes
    ├── __init__.py
    └── admin.py

db/init/                      # SQL init scripts run on first DB start
Dockerfile                    # Production multi-stage build
Dockerfile.dev                # Development build (source bind-mounted)
compose.yaml                  # Docker Compose for standalone development
docker-entrypoint.sh          # Container startup: init check → uv run fastapi dev
fai.sh / fai.ps1              # Helper scripts (see Operating Modes above)
pyproject.toml                # Project metadata and dependencies
uv.lock                       # Locked dependency manifest (commit this)
```

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
- The `ENVIRONMENT` env var controls runtime behaviour (`development` / `production`).
- Secrets and API keys must never be committed. Use `.env.example` as a template.

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
- Python version: `>=3.14` (specified in `pyproject.toml`).
- Add runtime deps to `[project] dependencies` in `pyproject.toml`.
- Dev dependencies go in `[dependency-groups]` in `pyproject.toml`.

## Environment Setup

```bash
cp .env.example .env   # then fill in API keys and credentials
```

Key env vars: `APP_NAME`, `APP_VERSION`, `DEBUG`, `ENVIRONMENT`, `DATABASE_URL`,
`SECRET_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.

When running standalone (`./fai.sh up`), `DATABASE_URL` defaults to
`postgresql+asyncpg://postgres:postgres@localhost:5432/fluent` (connecting to the local DB
inside the pod/compose network). Override in `.env` to point at the platform DB on port
5432 when running in service-only mode.

## Container Architecture

### Runtime detection

`fai.sh` / `fai.ps1` auto-detects the available runtime:

- **Podman present** → native Podman pod (`fluent-ai` pod, containers `fluent-ai-db` and `fluent-ai-ai`)
- **Docker present** → Docker Compose (`compose.yaml`)

### Podman pod layout

```
Pod: fluent-ai
  fluent-ai-db   postgres:16-alpine   host:5433 → pod:5432
  fluent-ai-ai   fluent-ai (local)    host:8200 → pod:8200
Volume: fluent-ai-pgdata
```

### Docker Compose layout

```
Service: db    postgres:16-alpine   host:5433 → container:5432
Service: ai    fluent-ai (built)    host:8200 → container:8200
```

### Security flags (AI container)

- `--read-only` — root filesystem is read-only
- `--user 1001:1001` — runs as non-root `python` user
- `--cap-drop ALL` — no Linux capabilities
- `--security-opt no-new-privileges:true`
- `--tmpfs /tmp` and `--tmpfs /app/.cache` — writable scratch space

### Source bind-mount

`src/` is mounted read-only into `/app/src`. FastAPI dev mode watches for changes and
hot-reloads automatically. `pyproject.toml`, `uv.lock`, and `docker-entrypoint.sh` are
also bind-mounted so dependency/entrypoint changes take effect without a full rebuild.

### First-run initialisation

`docker-entrypoint.sh` checks for `/tmp/.db-initialized` on startup. On first run it
executes any pending migrations/seeds, touches the sentinel, then starts the server.
The sentinel lives in `/tmp` (tmpfs) so it resets on each container restart — this is
intentional during development.
