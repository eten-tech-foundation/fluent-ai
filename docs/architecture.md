# FastAPI Project Architecture

How the modules in `src/app/` are shaped and what each layer may do. Where each feature lives is
in the [code map](code-map.md), and the behavior the code has to keep is in the
[domain rules](domain-rules.md).

## Standard Structure

```
src/app/
├── main.py              # App, lifespan, middleware, exception handlers, router registration
├── config.py            # Settings via pydantic-settings, loaded once by get_settings()
├── database.py          # Async engine, AsyncSessionLocal and get_db
├── dependencies.py      # Shared Depends() callables: get_db, require_api_key, require_admin,
│                        # and the getters for shared services
│
├── api/
│   └── v1/
│       ├── router.py    # Includes every endpoint module under its prefix
│       └── endpoints/   # api_keys, greek_room, jobs, suggestions, translations, tts
├── routers/
│   └── admin.py         # Older, unversioned /admin router
│
├── security/
│   └── auth.py          # API key checks (require_api_key, require_admin)
├── core/
│   ├── constants.py     # Job queue and worker tunables
│   ├── ai_clients/      # Model provider clients (google_gemini.py)
│   ├── config.py        # Placeholder: settings live in app/config.py
│   └── exceptions.py    # Placeholder: errors live in app/errors/
├── errors/              # Exception types, error codes, the error envelope, global handlers
├── logging/             # Structured logging on the stdlib logging module
├── middleware/
│   └── request_id.py    # RequestIDMiddleware
│
├── models/              # SQLAlchemy models, all in the ai schema (api_key.py, job.py)
├── schemas/             # Pydantic request/response models, one file per area
├── services/            # Business logic: api_key, jobs, suggestions, translation_service,
│                        # greek_room/, tts/
├── worker/
│   └── suggestion_processor.py   # Background loop that runs ai.jobs rows
├── crud/                # Empty: queries live in services/ and worker/
└── db/
    ├── base.py          # OwnedBase, the DeclarativeBase every model inherits from
    ├── migrations/      # Alembic env.py and versions/
    ├── seeds/           # Idempotent seeds (admin API keys)
    └── scripts/
        └── setup.py     # Migrations, then seeds (./fai.sh db:init)

tests/                   # pytest suites; tests/api/v1/ mirrors api/v1/endpoints/
src/tests/               # Suites for suggestions, the worker and the Gemini client
scripts/                 # bootstrap.py (roles, schema, grants), the docs check, smoke scripts
alembic.ini
pyproject.toml
.env.example
```

## Layer Responsibilities

### `main.py`

Wires the application together. It loads the settings and configures logging, creates the
`FastAPI` app with the shared error responses, adds the two middlewares, registers the exception
handlers and includes the two routers. The only routes it defines itself are `GET /` and
`GET /health`.

The lifespan builds the Greek Room service once, before the first request, and starts the
suggestion worker as an asyncio task when `ENABLE_SUGGESTION_WORKER` is on. On shutdown it cancels
in-flight speech generations first, then the worker.

The production image runs one uvicorn worker per container (the `Dockerfile` `CMD`), and that is
required: the speech generation heap and its dedup are per-process state. Scaling out means more
containers, each with its own suggestion worker.

### `config.py`

A single `Settings` class using `pydantic-settings`, loaded once through `get_settings()`
(`@lru_cache`). Every environment variable and secret is a field here, and validators refuse or
override values that are unsafe in production. Read settings through `get_settings()`, not
`os.environ`: only `config.py` itself and Alembic's `env.py` read the environment directly. Don't
hardcode values in source files. `.env.example` lists the variables.

### `database.py` and `dependencies.py`

`database.py` creates the async engine and `AsyncSessionLocal`. `get_db` yields one session per
request, commits when the handler returns and rolls back when it raises.

`dependencies.py` is what routers import: `get_db`, `require_api_key`, `require_admin`, and the
getters for shared services (`get_google_gemini_client`, `get_repeated_words_service`,
`get_tts_service`). Tests replace the same callables through `app.dependency_overrides`.

### `api/v1/`

The current HTTP boundary. Endpoint functions validate the request with a schema, call a service
and return a schema. Queries and business logic belong in `services/`. `api/v1/router.py`
includes each endpoint module under its prefix, and `main.py` includes only that router. The
version is a folder, not part of the URL: the routes are served at the root, such as
`/suggestions`.

### `routers/`

Holds `admin.py`, an older router that `main.py` includes on its own. New routes go in
`api/v1/endpoints/`.

### `security/auth.py`

The API key checks. `require_api_key` reads the `X-API-Key` header and returns the caller's
`ApiKey` record, and `require_admin` also needs the key to carry the `admin` permission. Hashing
and lookups live in `services/api_key.py`. Routers import both checks from `dependencies.py`.

### `core/`

`constants.py` holds the queue and worker tunables, and `ai_clients/google_gemini.py` wraps the
`google-genai` SDK for text generation. `config.py` and `exceptions.py` are placeholders with
comments only.

### `errors/`

Typed exceptions: `FluentAIException` and its subclasses in `exceptions.py` carry an `ErrorCode`
(`codes.py`), a message that is safe to show, optional details and an HTTP status.
`register_exception_handlers` in `handlers.py` handles those, request validation errors,
`HTTPException` and any other exception, and every handler answers with the `ErrorResponse`
envelope from `schemas.py`, which carries the request id. Raise one of these exceptions instead of
building an error response by hand.

### `logging/` and `middleware/`

Logging uses the stdlib `logging` module only. `configure_logging` writes JSON lines in production
and a readable format in development. Get a logger with `get_logger(__name__)`: its keyword
arguments become structured fields, and `SensitiveDataFilter` redacts fields with names like
`api_key`, `token` or `password`.

`RequestIDMiddleware` runs outermost. It takes `X-Request-ID` or `X-Correlation-ID` from the
request, or makes a new id, and echoes it as `X-Request-ID`. `LoggingMiddleware` logs the start
and end of each request, and every log line written while it runs carries that id.

### `models/` and `db/`

SQLAlchemy models, one file per table, with no business logic. Every model inherits `OwnedBase`
(`db/base.py`) and sets `{"schema": "ai"}`, and `db/base.py` imports each model module so Alembic's
autogenerate can see it. `db/migrations/env.py` ignores every schema except `ai` and keeps
`alembic_version` there.

Migrations are the only way schema changes reach a database. Never use
`Base.metadata.create_all()` outside tests. Deploys run `alembic upgrade head` before the new image
goes live. Seeds in `db/seeds/` must be idempotent. Local containers run them after the migrations
(`docker-entrypoint.sh`), and deploys don't run them.

To add a table:

1. Add the model in `src/app/models/<area>.py`, inheriting from `OwnedBase`.
2. Import the module in `src/app/db/base.py`.
3. Run `./fai.sh db:revision "create ai.<table>"` and review the generated file.
4. Run `./fai.sh db:migrate` to apply it locally.
5. If it needs seed data, add an idempotent seed in `src/app/db/seeds/` and call it from
   `run_all_seeds` in `src/app/db/seeds/runner.py`.

### `schemas/`

Pydantic models for requests and responses, one file per area, kept apart from the ORM models so
the API contract isn't tied to the tables. `tool_job.py` holds the envelope that tool endpoints
return (`ToolJobResponse`). Endpoints that answer with JSON declare a `response_model`.

### `services/`

Business logic, with no FastAPI request or response objects. Small areas are one module
(`api_key.py`, `jobs.py`, `suggestions.py`, `translation_service.py`), and larger ones are
packages (`greek_room/`, `tts/`). Services take the session, settings or clients they need as
arguments.

### `worker/`

`suggestion_processor.py` runs `worker_loop()` inside the web process. It claims queued rows from
`ai.jobs`, runs them and reports the results to fluent-api. It has no request session, so it opens
its own and commits after each step.

### `tests/`

pytest collects `tests/` and `src/tests/` (`testpaths` in `pyproject.toml`) with `src` on the
path. `tests/conftest.py` gives a `TestClient` with `get_db` replaced and the suggestion worker
off, and suites swap services and clients through `app.dependency_overrides` or fakes, so no test
needs a running database. New suites go in `tests/`, where `tests/api/v1/` mirrors
`api/v1/endpoints/`.

## Key Conventions

- **Thin endpoints, fat services.** A route function calls a service and returns its result.
- **Schemas ≠ models.** Never return an ORM model from a route. Declare a schema as the
  `response_model`.
- **`dependencies.py` is the seam.** Routers get the session, the caller's key and shared services
  from it, and tests override the same callables.
- **No `Base.metadata.create_all()` outside of tests.** Alembic owns the schema everywhere else.
- **All DB access is async.** Use `AsyncSession` and `await` throughout. Never block the event loop.
- **Only the `ai` schema.** Models and queries never touch another schema. Data that fluent-api
  owns comes over HTTP (see [Data ownership](domain-rules.md#data-ownership)).
