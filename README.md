# Fluent AI API

A FastAPI application built with uv for AI services that power the Fluent Ecosystem.

## Installation

```bash
# Install dependencies
uv sync

# Activate virtual environment
source .venv/bin/activate
```

## Running the Application

```bash
# Development server
uv run fastapi dev src/app/main.py --host 0.0.0.0

# Development server with custom port
uv run fastapi dev src/app/main.py --host 0.0.0.0 --port 8000

# Production server
uv run fastapi run src/app/main.py --host 0.0.0.0
```

## API Documentation

Once the server is running, you can access:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI Schema**: http://localhost:8000/openapi.json

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