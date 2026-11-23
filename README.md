# Fluent AI

Python 3.14 FastAPI service providing AI capabilities for the Fluent Ecosystem.
Managed with `uv`, containerized with Docker Compose (Docker) or native Podman pods (Podman).

## Operating Modes

| Mode | Command | DB port | When to use |
|---|---|---|---|
| **Standalone** | `./fai.sh up` | 5432 | Working on this service in isolation |
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
./fai.sh up             # Start DB on 5432 + AI service on 8200
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

### Checks before a PR

The Pre-merge workflow (`.github/workflows/pre-merge.yml`) runs these on the GitHub runner, not
in a container:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
./scripts/check-docs-structure.sh
```

They run the same way on the host with `uv`, which fetches Python 3.14 if you don't have it.
pytest needs no database, but the settings need `DATABASE_URL`, `API_BASE_URL` and
`API_SERVICE_KEY`. They come from `.env` after `./fai.sh setup`, and CI passes dummy values.
Inside the AI container, `./fai.sh lint`, `./fai.sh format:check`, `./fai.sh typecheck` and
`./fai.sh test` run the first four checks. The docs check only runs on the host, because the
container doesn't mount `docs/`.

The Pre-merge workflow skips draft PRs, so run these before you mark a PR ready. The Action pins
workflow (`.github/workflows/action-pins.yml`) runs on drafts too, and fails when a workflow uses
an action that isn't pinned to a full commit SHA.

### Database

| Command | Description |
|---|---|
| `./fai.sh db:psql` | Open interactive psql session |
| `./fai.sh db:init` | Run migrations, then seeds |
| `./fai.sh db:migrate` | Apply `ai`-schema migrations (`alembic upgrade head`) |
| `./fai.sh db:revision "<msg>"` | Generate a new autogenerate revision |
| `./fai.sh db:downgrade [target]` | Downgrade to a revision (default: one step back) |
| `./fai.sh db:history` | Show the Alembic revision history |
| `./fai.sh db:seed` | Run the `ai`-schema seeds (idempotent) |

## Architecture

### Container layout

**Podman (native pod):**
```
Pod: fluent-ai
  fluent-ai-db   postgres:16-alpine   host:5432 → pod:5432
  fluent-ai-ai   fluent-ai (local)    host:8200 → pod:8200
Volume: fluent-ai-pgdata
```

**Docker Compose:**
```
db   postgres:16-alpine   host:5432 → container:5432
ai   fluent-ai (built)    host:8200 → container:8200
```

### Key design decisions

- **Source bind-mount** — `src/` is mounted into the container so FastAPI dev mode
  hot-reloads on every file save without a rebuild.
- **Standalone DB on 5432** — same port as the platform/API shared DB. Don't run the
  standalone AI stack at the same time as the platform (both bind host 5432). Override
  with `DB_PORT`.
- **Read-only container** — AI container runs with `--read-only`, `--cap-drop ALL`, and
  `--user 1001:1001`. Writable scratch space is provided via `--tmpfs /tmp` and
  `--tmpfs /app/.cache`.
- **Database setup on start** — `docker-entrypoint.sh` runs the bootstrap, the
  migrations and the seeds every time the dev container starts, then starts the server.
  Set `SKIP_DB_BOOTSTRAP=1` to skip them, for example in a one-off shell. The production
  image doesn't run them; deploys run the migrations.

## Project Structure

The app lives in `src/app/`. The [code map](docs/code-map.md) says what each module does and what
it calls, and [docs/architecture.md](docs/architecture.md) says how the layers fit together.

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
| `GET` | `/health` | — | Health check; the deploy workflows wait for its `commit` |

The [code map](docs/code-map.md#http) lists the other routes by area, and Swagger UI at `/docs`
documents each one.

### API Key lifecycle

Keys are created by an admin and returned with a `raw_key` field exactly once — it is never stored and cannot be retrieved again. All subsequent responses use `ApiKeyInfo`, which omits `raw_key` and `key_hash`.

```bash
# Create a key
curl -X POST http://localhost:8200/api-keys/ \
  -H "X-API-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-service", "permissions": [], "owner_user_id": 1}'

# Use the returned raw_key for subsequent requests
curl http://localhost:8200/api-keys/me \
  -H "X-API-Key: fai_<returned_raw_key>"
```

## Production Build

```bash
docker build -t fluent-ai .
docker run -p 8200:8200 --env-file .env fluent-ai
```

## Releases / Versioning

This project uses Calendar Versioning (CalVer) with the format `YY.MM.SERIAL`. The canonical tag/commit format keeps the leading zero on the month (e.g., `v26.07.1`); `pyproject.toml`'s `version` field is Python-normalized and drops it (e.g., `26.7.1` — see [`docs/calver-versioning.md`](docs/calver-versioning.md)). Currently, releases for `fluent-ai` are manual. To release a new version:
1. Update `version` in `pyproject.toml` to the current Python-normalized `YY.M.SERIAL` (e.g. `26.7.1`; incrementing serial if a release this month already exists).
2. Commit the change (e.g. `chore(release): v26.07.1`).
3. Tag the commit (e.g. `v26.07.1`) and push.
