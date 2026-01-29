# syntax=docker/dockerfile:1

FROM python:3.14-slim AS base

# Prevent Python from writing bytecode and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-install-project --no-dev

# Copy application source
COPY src/ ./src/

# Install the project itself
RUN uv sync --frozen --no-dev

# Expose the application port
EXPOSE 8200

# Run the application
CMD ["uv", "run", "fastapi", "run", "src/app/main.py", "--host", "0.0.0.0", "--port", "8200"]
