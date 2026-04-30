# FastAPI Project Architecture

## Standard Structure

```
project/
├── src/app/
│   ├── __init__.py
│   ├── main.py              # FastAPI instantiation, middleware, router registration only
│   ├── config.py            # Settings via pydantic-settings (env vars, secrets)
│   ├── dependencies.py      # Shared FastAPI Depends() callables (get_db, get_current_user)
│   │
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py    # Aggregates all v1 endpoint routers
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── projects.py
│   │           ├── api_keys.py
│   │           └── users.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── security.py      # Auth logic (API key hashing, JWT if needed)
│   │   └── exceptions.py    # Custom exception handlers registered on the app
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py          # SQLAlchemy DeclarativeBase
│   │   ├── session.py       # Async engine and AsyncSessionLocal factory
│   │   └── migrations/      # Alembic migrations
│   │       └── versions/
│   │
│   ├── models/              # SQLAlchemy ORM models (one file per domain)
│   │   ├── __init__.py
│   │   ├── project.py
│   │   └── api_key.py
│   │
│   ├── schemas/             # Pydantic request/response models (one file per domain)
│   │   ├── __init__.py
│   │   ├── projects.py
│   │   └── api_key.py
│   │
│   └── services/            # Business logic, decoupled from HTTP layer
│       ├── __init__.py
│       └── api_key.py
│
├── tests/
│   ├── conftest.py          # Fixtures: test client, test DB session override
│   └── api/
│       └── v1/
│           ├── test_projects.py
│           └── test_api_keys.py
│
├── alembic.ini
├── pyproject.toml
└── .env.example
```

## Layer Responsibilities

### `main.py`
Wires the application together. Instantiates `FastAPI`, registers routers, attaches middleware and exception handlers. Contains no route logic.

### `config.py`
Single `Settings` class using `pydantic-settings`. Loaded once via `@lru_cache`. All environment variables and secrets live here. Never hardcode values in source files.

### `dependencies.py`
Centralized `Depends()` callables shared across routers: `get_db`, `get_current_api_key`, `require_admin`. Keeps routers thin and makes auth logic swappable.

### `api/v1/`
HTTP boundary. Endpoint functions handle request validation, call into `services/`, and shape the HTTP response. No DB queries or business logic belong here. Versioning (`v1/`) allows the API contract to evolve without breaking existing callers.

### `api/v1/router.py`
Single `APIRouter` that `include_router`s each endpoint module. `main.py` imports only this one router, keeping it ignorant of individual endpoint files.

### `core/security.py`
Authentication mechanics: key hashing, token validation, permission checks. Imported by `dependencies.py`. Has no FastAPI imports — pure Python logic that's easy to unit test.

### `core/exceptions.py`
Custom `HTTPException` subclasses and exception handlers. Registered on the `FastAPI` app in `main.py` via `app.add_exception_handler(...)`.

### `db/base.py`
The single `DeclarativeBase` subclass that all ORM models inherit from. Import all models here before running Alembic so it can see them for autogenerate.

### `db/session.py`
`create_async_engine` and `async_sessionmaker`. Provides `get_db` as an `AsyncGenerator` for use in `dependencies.py`.

### `db/migrations/`
Alembic migration files. `alembic.ini` at project root points here. Migrations are the only way schema changes reach the database — never use `Base.metadata.create_all()` in production.

### `models/`
SQLAlchemy ORM models. One file per domain object. Each model maps to exactly one database table. No business logic. No Pydantic here.

### `schemas/`
Pydantic models for API input/output. One file per domain. Kept separate from ORM models to avoid coupling the API contract to the DB schema. Use `model_config = ConfigDict(from_attributes=True)` to support ORM→schema conversion.

### `services/`
Business logic. Functions that accept domain objects or primitive values and return domain objects. No FastAPI imports, no `Request`/`Response`. Calls into `models/` and `db/session.py` directly. Easy to unit test.

### `tests/`
- `conftest.py` — shared fixtures: `TestClient`, database session override via `app.dependency_overrides`.
- Mirror the `api/v1/` structure in `tests/api/v1/` so test files are easy to find.

## Key Conventions

- **Thin endpoints, fat services.** Route functions call one service function and return its result.
- **Schemas ≠ models.** Never return an ORM model directly from a route — always go through a Pydantic schema.
- **`dependencies.py` is the auth seam.** Swap auth logic by changing one file, not hunting through routers.
- **No `Base.metadata.create_all()` outside of tests.** Alembic owns the schema in all other environments.
- **All DB access is async.** Use `AsyncSession` and `await` throughout. Never block the event loop.
