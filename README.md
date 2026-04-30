# Fluent AI

Python 3.14 FastAPI service providing AI capabilities for the Fluent Ecosystem.
Managed with `uv`, containerized with Docker Compose (Docker) or native Podman pods (Podman).

## Operating Modes

| Mode | Command | DB port | When to use |
|---|---|---|---|
| **Standalone** | `./fai.sh up` | 5433 | Working on this service in isolation |
| **Service-only** | `./fai.sh up ai` | — (external) | Platform's DB is already running |
| **Ecosystem** | `./fluent.sh up` (fluent-platform) | 5432 | Full integration work |

To connect a standalone service to the platform DB, set `DATABASE_URL` in `.env` to
`postgresql+asyncpg://postgres:postgres@localhost:5432/fluent` and run `./fai.sh up ai`.

## Quick Start

### Prerequisites

- [Podman](https://podman.io/) **or** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- (Optional) Python 3.14 + `uv` for local development outside containers

### Setup

```bash
./fai.sh setup          # Copy .env.example → .env
# Fill in API keys and credentials in .env
./fai.sh up             # Start DB on 5433 + AI service on 8200
curl http://localhost:8200/health
```

Windows: use `fai.ps1` with the same commands.

## Commands

### Container management

| Command | Description |
|---|---|
| `./fai.sh up [service]` | Start services — `db`, `ai`, or all (default) |
| `./fai.sh down [service]` | Stop and remove services (default: all) |
| `./fai.sh restart [service]` | Restart services (default: all) |
| `./fai.sh logs [service]` | Tail logs — `db`, `ai`, or all (default) |
| `./fai.sh status` | Show pod/container status (all states) |
| `./fai.sh shell [service]` | Shell into container (`ai` default; `db` opens psql) |
| `./fai.sh build [service]` | Rebuild images without cache |
| `./fai.sh clean [service]` | Remove containers and volumes (default: all) |
| `./fai.sh fresh` | Remove containers, volumes, and image |
| `./fai.sh setup` | Copy `.env.example` → `.env` if missing |

### Development (runs inside AI container)

| Command | Description |
|---|---|
| `./fai.sh test` | Run pytest test suite |
| `./fai.sh lint` | Run ruff linter |
| `./fai.sh lint:fix` | Run ruff linter with auto-fix |
| `./fai.sh format` | Format code with ruff |
| `./fai.sh format:check` | Check formatting without writing |
| `./fai.sh typecheck` | Run mypy type checking |
| `./fai.sh run <cmd>` | Run any `uv run` command in the AI container |

### Database

| Command | Description |
|---|---|
| `./fai.sh db:psql` | Open interactive psql session |
| `./fai.sh db:migrate` | Run schema migrations (TODO) |
| `./fai.sh db:seed` | Run seed data (TODO) |

## Architecture

### Container layout

**Podman (native pod):**
```
Pod: fluent-ai
  fluent-ai-db   postgres:16-alpine   host:5433 → pod:5432
  fluent-ai-ai   fluent-ai (local)    host:8200 → pod:8200
Volume: fluent-ai-pgdata
```

**Docker Compose:**
```
db   postgres:16-alpine   host:5433 → container:5432
ai   fluent-ai (built)    host:8200 → container:8200
```

### Key design decisions

- **Source bind-mount** — `src/` is mounted into the container so FastAPI dev mode
  hot-reloads on every file save without a rebuild.
- **Standalone DB on 5433** — avoids port conflict with the platform orchestrator's
  shared DB on 5432. Override with `DB_PORT=5432` if needed.
- **Read-only container** — AI container runs with `--read-only`, `--cap-drop ALL`, and
  `--user 1001:1001`. Writable scratch space is provided via `--tmpfs /tmp` and
  `--tmpfs /app/.cache`.
- **First-run init** — `docker-entrypoint.sh` checks `/tmp/.db-initialized` on each
  start. On first run it executes pending migrations/seeds then starts the server. The
  sentinel resets on restart (intentional in dev).

## Project Structure

```
src/app/
├── main.py              # FastAPI app, router mounting
├── config.py            # Pydantic BaseSettings + cached getter
├── dependencies.py      # Shared Depends() callables (get_db, require_api_key, require_admin)
├── api/
│   └── v1/
│       ├── router.py    # Aggregates all v1 endpoint routers
│       └── endpoints/
│           └── api_keys.py   # /api-keys/* route handlers
├── core/
│   └── exceptions.py    # Custom exception types (scaffold)
├── db/                  # DB infrastructure scaffold (session, base, migrations)
├── internal/
│   ├── models.py        # SQLAlchemy ORM models (Project, ApiKey)
│   └── admin.py         # Admin router (not yet mounted)
├── models/              # Standard model location (scaffold)
├── routers/
│   └── projects.py      # /projects/* route handlers
├── schemas/
│   ├── api_key.py       # ApiKeyCreate, ApiKeyCreated, ApiKeyInfo, ApiKeyUpdate
│   └── projects.py      # ProjectResponse, ProjectListResponse
├── security/
│   └── auth.py          # require_api_key, require_admin dependencies
└── services/
    └── api_key.py       # API key business logic (create, hash, revoke, etc.)

tests/
└── api/v1/
    └── test_api_keys.py # Endpoint tests for /api-keys/*

db/init/                 # SQL scripts run on first DB start
Dockerfile               # Production multi-stage build
Dockerfile.dev           # Development build
compose.yaml             # Docker Compose (standalone dev)
docker-entrypoint.sh     # Container startup script
fai.sh / fai.ps1         # Helper scripts
```

## API

Once running, visit:

- **Swagger UI**: http://localhost:8200/docs
- **ReDoc**: http://localhost:8200/redoc
- **OpenAPI JSON**: http://localhost:8200/openapi.json

### Authentication

Protected endpoints require an `X-API-Key` header with a valid API key:

```
X-API-Key: fai_your_key_here
```

Admin-only endpoints additionally require the key to have the `"admin"` permission.

### Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | — | Welcome message |
| `GET` | `/health` | — | Health check |
| `GET` | `/projects/` | API key | List projects (paginated) |
| `GET` | `/projects/{id}` | API key | Get project by ID |
| `GET` | `/projects/_verify-permissions` | Admin | Verify DB role grants |
| `POST` | `/api-keys/` | Admin | Create a new API key |
| `GET` | `/api-keys/` | Admin | List all API keys |
| `PATCH` | `/api-keys/{key_id}` | Admin | Update key name, permissions, or expiry |
| `DELETE` | `/api-keys/{key_id}` | Admin | Revoke an API key |
| `GET` | `/api-keys/me` | API key | Get current key info |

### API Key lifecycle

Keys are created by an admin and returned with a `raw_key` field exactly once — it is never stored and cannot be retrieved again. All subsequent responses use `ApiKeyInfo`, which omits `raw_key` and `key_hash`.

```bash
# Create a key
curl -X POST http://localhost:8200/api-keys/ \
  -H "X-API-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-service", "permissions": []}'

# Use the returned raw_key for subsequent requests
curl http://localhost:8200/api-keys/me \
  -H "X-API-Key: fai_<returned_raw_key>"
```

## Production Build

```bash
docker build -t fluent-ai .
docker run -p 8200:8200 --env-file .env fluent-ai
```
