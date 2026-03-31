#!/usr/bin/env bash
set -euo pipefail

# ── Runtime detection (prefer Podman) ──────────────────────────────────────────

detect_runtime() {
  if command -v podman &>/dev/null && command -v podman-compose &>/dev/null; then
    COMPOSE_CMD="podman-compose"
  elif command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
  elif command -v docker &>/dev/null && command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
  else
    echo "Error: No container runtime found."
    echo "Install one of:"
    echo "  - Podman + podman-compose"
    echo "  - Docker Desktop (includes docker compose V2)"
    echo "  - Docker Engine + docker-compose"
    exit 1
  fi
}

detect_runtime

# ── Commands ───────────────────────────────────────────────────────────────────

cmd="${1:-help}"
shift || true

case "$cmd" in
  up)
    $COMPOSE_CMD up -d --build "$@"
    ;;
  down)
    $COMPOSE_CMD down "$@"
    ;;
  restart)
    $COMPOSE_CMD restart "$@"
    ;;
  logs)
    $COMPOSE_CMD logs -f "$@"
    ;;
  status)
    $COMPOSE_CMD ps "$@"
    ;;
  db:migrate)
    echo "Running fluent-ai migrations..."
    echo "TODO: Add migration command when ai schema migrations are set up"
    # $COMPOSE_CMD exec ai uv run alembic upgrade head
    ;;
  db:seed)
    echo "Running fluent-ai seeds..."
    echo "TODO: Add seed command when ai seeds are created"
    # $COMPOSE_CMD exec ai uv run python src/db/seeds/seed.py
    ;;
  db:psql)
    $COMPOSE_CMD exec db psql -U postgres -d fluent
    ;;
  shell)
    service="${1:-ai}"
    if [ "$service" = "db" ]; then
      $COMPOSE_CMD exec db psql -U postgres -d fluent
    else
      $COMPOSE_CMD exec "$service" sh
    fi
    ;;
  test)
    $COMPOSE_CMD exec ai uv run pytest "$@"
    ;;
  run)
    $COMPOSE_CMD exec ai uv run "$@"
    ;;
  clean)
    echo "This will remove all containers AND volumes (full DB reset)."
    read -rp "Continue? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
      $COMPOSE_CMD down -v
      rm -f .db-initialized
    else
      echo "Aborted."
    fi
    ;;
  build)
    $COMPOSE_CMD build --no-cache "$@"
    ;;
  setup)
    if [ ! -f .env ]; then
      cp .env.example .env
      echo "Created .env from .env.example"
    else
      echo ".env already exists, skipping copy."
    fi
    echo "Remember to fill in API keys and other credentials in .env"
    ;;
  help|*)
    cat <<'USAGE'
Usage: ./fai.sh <command> [args]

Commands:
  up              Start containers (build + detached)
  down            Stop and remove containers
  restart         Restart containers
  logs [service]  Tail logs (default: all services)
  status          Show container status
  db:migrate      Run AI schema migrations
  db:seed         Seed AI tables
  db:psql         Open psql session
  shell [service] Open a shell (ai default, db opens psql)
  test            Run pytest test suite inside the AI container
  run <command>   Run a uv command inside the AI container
  clean           Remove containers and volumes (full DB reset)
  build           Rebuild containers without cache
  setup           Copy .env.example → .env if missing
USAGE
    ;;
esac
