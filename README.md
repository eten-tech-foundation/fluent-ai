# Fluent AI API

A FastAPI application built with uv for AI services that power the Fluent Ecosystem.

## Local Development with Containers

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) **or** [Podman](https://podman.io/) with `podman-compose`
- (Optional) Python/uv on host for direct development

### Quick Start

```bash
./fai.sh setup          # Create .env from .env.example
# Fill in API keys and other credentials in .env
./fai.sh up             # Start AI service + PostgreSQL containers
curl http://localhost:8200/health
```

Windows users: use `fai.ps1` with the same commands.

### All Commands

| Command | Description |
|---|---|
| `./fai.sh up` | Build and start containers in detached mode |
| `./fai.sh down` | Stop and remove containers |
| `./fai.sh restart` | Restart containers |
| `./fai.sh logs [service]` | Tail container logs (all or specific service) |
| `./fai.sh status` | Show container status |
| `./fai.sh db:migrate` | Run AI schema migrations |
| `./fai.sh db:seed` | Seed AI tables |
| `./fai.sh db:psql` | Open psql session |
| `./fai.sh shell [service]` | Shell into a container (`ai` default, `db` opens psql) |
| `./fai.sh test` | Run pytest test suite inside the container |
| `./fai.sh run <command>` | Run a uv command inside the AI container |
| `./fai.sh clean` | Remove containers **and** volumes (full DB reset) |
| `./fai.sh build` | Rebuild containers without cache |
| `./fai.sh setup` | Copy `.env.example` → `.env` if missing |

### Architecture Notes

- **Bind mount**: Source code (`src/`) is mounted into the container so FastAPI dev mode picks up changes instantly.
- **Shared database**: Uses the shared `fluent` database with schema isolation (`ai` schema). The `db/init/` scripts set up all roles and privileges.
- **DATABASE_URL override**: `.env` keeps `localhost` for host tools (psql). `compose.yaml` overrides it to `db` for container networking.
- **First-run init**: `docker-entrypoint.sh` uses a sentinel file (`.db-initialized`) to run migrations and seeds on first startup only.
- **Standalone vs ecosystem**: The standalone `compose.yaml` includes its own Postgres. When running via `fluent-platform`, the shared database is used instead.

### Production Build

```bash
docker build -t fluent-ai .
docker run -p 8200:8200 --env-file .env fluent-ai
```

---

## API Documentation

Once the server is running, you can access:

- **Swagger UI**: http://localhost:8200/docs
- **ReDoc**: http://localhost:8200/redoc
- **OpenAPI Schema**: http://localhost:8200/openapi.json

## Project Structure

```
src/
├── app/
│   ├── __init__.py
│   ├── main.py              # Main FastAPI application
│   ├── dependencies.py      # Common dependencies
│   ├── internal/
│   │   ├── __init__.py
│   │   └── admin.py         # Admin routes
│   └── routers/
│       ├── __init__.py
│       ├── items.py         # Item management routes
│       └── users.py         # User management routes
└── tests/                   # Test files
```

## Available Endpoints

### Root
- `GET /` - Welcome message
- `GET /health` - Health check

### Items (requires X-Token header)
- `GET /items/` - List all items
- `GET /items/{item_id}` - Get specific item
- `POST /items/` - Create new item

### Users
- `GET /users/` - List all users
- `GET /users/{username}` - Get specific user
- `POST /users/` - Create new user

### Admin
- `GET /admin/stats` - Admin statistics
- `GET /admin/health` - Admin health check

## Development

This project uses:
- **FastAPI** - Modern, fast web framework for building APIs
- **uv** - Python package manager
- **Pydantic** - Data validation using Python type annotations

## TODO:
- [x] Add environment configuration management
- [ ] Set up PostgreSQL database connection with SQLAlchemy or SQLModel - investigate the merits of using SQLModel.
- [ ] Add Alembic for database migrations
- [ ] Implement structured logging with proper log levels
- [ ] Add HTTP client for external AI service integrations
- [ ] Create error handling and custom exception classes
- [ ] Add request/response models and validation schemas
- [ ] Implement authentication/authorization middleware
- [ ] Add health checks for database and external services
- [ ] Set up testing framework with pytest and test database
- [x] Add Docker configuration for development and production
- [ ] Implement rate limiting and request throttling
