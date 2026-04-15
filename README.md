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
├── dependencies.py      # Shared dependency functions
├── core/
│   └── config.py        # Core configuration
├── routers/
│   ├── items.py         # Item routes
│   └── users.py         # User routes
└── internal/
    └── admin.py         # Admin routes

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

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Welcome message |
| `GET` | `/health` | Health check |
| `GET` | `/items/` | List items (requires `X-Token`) |
| `GET` | `/items/{item_id}` | Get item |
| `POST` | `/items/` | Create item |
| `GET` | `/users/` | List users |
| `GET` | `/users/{username}` | Get user |
| `POST` | `/users/` | Create user |
| `GET` | `/admin/stats` | Admin stats |
| `GET` | `/admin/health` | Admin health |

## Production Build

```bash
docker build -t fluent-ai .
docker run -p 8200:8200 --env-file .env fluent-ai
```
