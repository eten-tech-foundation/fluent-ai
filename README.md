# Fluent AI API

A FastAPI application built with uv for AI services that power the Fluent Ecosystem.

## Quick Start (Docker/Podman)

The simplest way to run Fluent AI—no local dependencies required except Docker or Podman.

The API runs on **port 8200** by default: http://localhost:8200

### Prerequisites

**macOS/Linux:** Make the CLI script executable (one-time setup):
```bash
chmod +x fai
```

**Windows:** No additional setup required—`fai.bat` is ready to use.

### Development Mode

**macOS/Linux:**
```bash
# Setup: Copy and configure environment
cp .env.dev.example .env.dev

# Option 1: Dev with cloud database
./fai start

# Option 2: Dev with local PostgreSQL container
./fai --local-db start
```

**Windows (Command Prompt or PowerShell):**
```cmd
REM Setup: Copy and configure environment
copy .env.dev.example .env.dev

REM Option 1: Dev with cloud database
fai start

REM Option 2: Dev with local PostgreSQL container
fai --local-db start
```

### Production Mode

**macOS/Linux:**
```bash
# Setup: Copy and configure environment
cp .env.prod.example .env.prod

# Start production
./fai --prod start
```

**Windows:**
```cmd
copy .env.prod.example .env.prod
fai --prod start
```

### CLI Reference

| Command | Description |
|---------|-------------|
| `fai start` | Start the application (builds if needed) |
| `fai stop` | Stop the application |
| `fai restart` | Restart the application |
| `fai logs` | View application logs |
| `fai status` | Show running containers |
| `fai shell` | Open a shell in the app container |
| `fai build` | Build/rebuild images |
| `fai clean` | Remove containers, volumes, and images |

### CLI Options

| Option | Description |
|--------|-------------|
| `--dev` | Use development environment (default) |
| `--prod` | Use production environment |
| `--local-db` | Include local PostgreSQL container |

### Examples

**macOS/Linux:**
```bash
./fai start                  # Dev mode, cloud DB
./fai --local-db start       # Dev mode, local PostgreSQL
./fai --prod start           # Production mode
./fai --local-db logs        # View logs with local DB running
```

**Windows:**
```cmd
fai start                    :: Dev mode, cloud DB
fai --local-db start         :: Dev mode, local PostgreSQL
fai --prod start             :: Production mode
fai --local-db logs          :: View logs with local DB running
```

### Database Options

**Cloud Database (default):** Set `DATABASE_URL` in `.env.dev` to your cloud PostgreSQL instance.

**Local PostgreSQL:** Use `--local-db` flag to spin up a containerized PostgreSQL alongside the app.

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
