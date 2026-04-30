#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Runtime detection (prefer native Podman pods) ─────────────────────────────

detect_runtime() {
  if command -v podman &>/dev/null; then
    RUNTIME_MODE="podman-pod"
    RUNTIME="podman"
  elif command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    RUNTIME_MODE="docker-compose"
    COMPOSE_CMD="docker compose"
  elif command -v docker &>/dev/null && command -v docker-compose &>/dev/null; then
    RUNTIME_MODE="docker-compose"
    COMPOSE_CMD="docker-compose"
  else
    echo "Error: No container runtime found."
    echo "Install one of:"
    echo "  - Podman (native pods)"
    echo "  - Docker Desktop (includes docker compose V2)"
    echo "  - Docker Engine + docker-compose"
    exit 1
  fi
}

detect_runtime

# ── Color helpers ─────────────────────────────────────────────────────────────

YELLOW='\033[1;33m'
GREEN='\033[1;32m'
RED='\033[1;31m'
NC='\033[0m'

echo_running() { echo -e "${YELLOW}>>> $1${NC}"; }
echo_success() { echo -e "${GREEN}>>> $1${NC}"; }
echo_error()   { echo -e "${RED}>>> $1${NC}"; }

# ── Podman pod configuration ──────────────────────────────────────────────────

POD_NAME="fluent-ai"
# 5433 avoids conflict with the platform orchestrator's shared DB on 5432.
# Use DB_PORT=5432 (or set DATABASE_URL in .env) to connect to the platform DB instead.
DB_PORT="${DB_PORT:-5433}"
AI_PORT="${AI_PORT:-8200}"

# ── Podman pod management ─────────────────────────────────────────────────────

pod_create() {
  if $RUNTIME pod exists "$POD_NAME" 2>/dev/null; then
    echo_success "Pod $POD_NAME already exists"
    return
  fi
  echo_running "Creating pod $POD_NAME..."
  $RUNTIME pod create \
    --name "$POD_NAME" \
    --share "net,ipc,uts" \
    -p "${DB_PORT}:5432" \
    -p "${AI_PORT}:8200"
}

pod_destroy() {
  if $RUNTIME pod exists "$POD_NAME" 2>/dev/null; then
    echo_running "Removing pod $POD_NAME..."
    $RUNTIME pod rm "$POD_NAME" -f
  fi
}

create_volumes() {
  echo_running "Creating volumes..."
  $RUNTIME volume create fluent-ai-pgdata 2>/dev/null || true
}

wait_for_db() {
  echo_running "Waiting for database to be ready..."
  while ! $RUNTIME exec fluent-ai-db pg_isready -U postgres -d fluent 2>/dev/null; do
    sleep 2
  done
  echo_success "Database is ready"
}

# ── Podman container start functions ──────────────────────────────────────────

start_db_container() {
  if $RUNTIME container exists fluent-ai-db 2>/dev/null; then
    echo_success "Database container already exists"
    return
  fi
  echo_running "Starting database container..."
  $RUNTIME run -d \
    --name fluent-ai-db \
    --pod "$POD_NAME" \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD=postgres \
    -e POSTGRES_DB=fluent \
    -v fluent-ai-pgdata:/var/lib/postgresql/data \
    -v "$SCRIPT_DIR/db/init:/docker-entrypoint-initdb.d" \
    --health-cmd "pg_isready -U postgres -d fluent" \
    --health-interval 5s \
    --health-timeout 5s \
    --health-retries 5 \
    docker.io/postgres:16-alpine
  echo_success "Database container started"
}

start_ai_container() {
  if $RUNTIME container exists fluent-ai-ai 2>/dev/null; then
    echo_success "AI container already exists"
    return
  fi

  echo_running "Building AI image..."
  $RUNTIME build -t fluent-ai "$SCRIPT_DIR" -f Dockerfile.dev

  local -a env_flags=(
    -e "DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/fluent"
    -e "ENVIRONMENT=development"
    -e "DEBUG=true"
    -e "UV_CACHE_DIR=/app/.cache/uv"
  )
  if [[ -f "$SCRIPT_DIR/.env" ]]; then
    env_flags+=(--env-file "$SCRIPT_DIR/.env")
  fi

  echo_running "Starting AI container..."
  $RUNTIME run -d \
    --name fluent-ai-ai \
    --pod "$POD_NAME" \
    "${env_flags[@]}" \
    -v "$SCRIPT_DIR/src:/app/src:ro" \
    -v "$SCRIPT_DIR/tests:/app/tests:ro" \
    -v "$SCRIPT_DIR/pyproject.toml:/app/pyproject.toml:ro" \
    -v "$SCRIPT_DIR/uv.lock:/app/uv.lock:ro" \
    -v "$SCRIPT_DIR/docker-entrypoint.sh:/app/docker-entrypoint.sh:ro" \
    --tmpfs /tmp:nosuid,size=64m \
    --tmpfs /app/.cache:noexec,nosuid,size=128m \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --user 1001:1001 \
    --read-only \
    fluent-ai
  echo_success "AI container started"
}

# ── Podman command functions ───────────────────────────────────────────────────

podman_up() {
  local service="${1:-all}"
  case "$service" in
    all)
      create_volumes
      pod_create
      start_db_container
      wait_for_db
      start_ai_container
      echo_success "All services started!"
      ;;
    db)
      create_volumes
      pod_create
      start_db_container
      echo_success "Database started!"
      ;;
    ai)
      pod_create
      start_ai_container
      echo_success "AI service started!"
      ;;
    *)
      echo_error "Unknown service: $service (use: db, ai, or omit for all)"
      exit 1
      ;;
  esac
}

podman_down() {
  local service="${1:-all}"
  if [ "$service" = "all" ]; then
    pod_destroy
    echo_success "All services stopped."
  else
    echo_running "Stopping $service..."
    $RUNTIME rm -f "fluent-ai-$service" 2>/dev/null || true
    echo_success "$service stopped."
  fi
}

podman_restart() {
  local service="${1:-all}"
  if [ "$service" = "all" ]; then
    pod_destroy
    podman_up all
  else
    echo_running "Restarting $service..."
    $RUNTIME rm -f "fluent-ai-$service" 2>/dev/null || true
    case "$service" in
      db) start_db_container ;;
      ai) start_ai_container ;;
      *) echo_error "Unknown service: $service"; exit 1 ;;
    esac
    echo_success "Restarted $service"
  fi
}

podman_logs() {
  local service="${1:-}"
  if [ -z "$service" ]; then
    $RUNTIME pod logs -f "$POD_NAME"
  else
    # Route through pod logs --container to avoid direct name-resolution bugs
    # in some podman builds where 'podman logs <hyphenated-name>' fails.
    $RUNTIME pod logs --container "fluent-ai-$service" -f "$POD_NAME"
  fi
}

podman_status() {
  $RUNTIME pod ps
  if $RUNTIME pod exists "$POD_NAME" 2>/dev/null; then
    echo ""
    echo "Containers in pod $POD_NAME (all states):"
    $RUNTIME ps -a --filter "pod=$POD_NAME"
  fi
}

podman_shell() {
  local service="${1:-ai}"
  if [ "$service" = "db" ]; then
    $RUNTIME exec -it fluent-ai-db psql -U postgres -d fluent
  else
    $RUNTIME exec -it "fluent-ai-$service" sh
  fi
}

podman_exec_ai() {
  if ! $RUNTIME ps --format "{{.Names}}" 2>/dev/null | grep -qx "fluent-ai-ai"; then
    echo_error "AI container is not running. Run './fai.sh up ai' first."
    exit 1
  fi
  $RUNTIME exec fluent-ai-ai "$@"
}

podman_clean() {
  local service="${1:-all}"
  if [ "$service" = "all" ]; then
    pod_destroy
    $RUNTIME volume rm fluent-ai-pgdata 2>/dev/null || true
    echo_success "All containers and volumes removed."
  else
    $RUNTIME rm -f "fluent-ai-$service" 2>/dev/null || true
    echo_success "$service container removed."
  fi
}

podman_fresh() {
  pod_destroy
  $RUNTIME volume rm fluent-ai-pgdata 2>/dev/null || true
  $RUNTIME rmi -f fluent-ai 2>/dev/null || true
  echo_success "Removed all containers, volumes, and images."
}

podman_build() {
  local service="${1:-ai}"
  if [ "$service" = "ai" ] || [ "$service" = "all" ]; then
    echo_running "Building AI image..."
    $RUNTIME build -t fluent-ai "$SCRIPT_DIR" -f Dockerfile.dev
    echo_success "AI image built."
  else
    echo_error "Unknown buildable service: $service (only 'ai' has a custom image)"
    exit 1
  fi
}

podman_db_psql() {
  $RUNTIME exec -it fluent-ai-db psql -U postgres -d fluent
}

# ── Docker Compose command functions ──────────────────────────────────────────

compose_up() {
  local service="${1:-}"
  if [ -z "$service" ] || [ "$service" = "all" ]; then
    # Start everything — compose resolves depends_on and waits for DB health
    $COMPOSE_CMD up -d --build
  else
    # Start only the requested service; the caller is responsible for any deps
    $COMPOSE_CMD up -d --build --no-deps "$service"
  fi
}

compose_down() {
  local service="${1:-}"
  if [ -z "$service" ] || [ "$service" = "all" ]; then
    $COMPOSE_CMD down
  else
    $COMPOSE_CMD rm -sf "$service"
  fi
}

compose_restart() {
  local service="${1:-}"
  if [ -z "$service" ] || [ "$service" = "all" ]; then
    $COMPOSE_CMD restart
  else
    $COMPOSE_CMD restart "$service"
  fi
}

compose_logs() {
  $COMPOSE_CMD logs -f "$@"
}

compose_status() {
  $COMPOSE_CMD ps
}

compose_shell() {
  local service="${1:-ai}"
  if [ "$service" = "db" ]; then
    $COMPOSE_CMD exec db psql -U postgres -d fluent
  else
    $COMPOSE_CMD exec "$service" sh
  fi
}

compose_exec_ai() {
  $COMPOSE_CMD exec ai "$@"
}

compose_clean() {
  local service="${1:-all}"
  if [ "$service" = "all" ]; then
    $COMPOSE_CMD down -v
    echo_success "All containers and volumes removed."
  else
    $COMPOSE_CMD rm -sf "$service"
    echo_success "$service container removed."
  fi
}

compose_fresh() {
  $COMPOSE_CMD down -v --rmi local --remove-orphans
  echo_success "Removed all containers, volumes, and images."
}

compose_build() {
  local service="${1:-}"
  if [ -z "$service" ] || [ "$service" = "all" ]; then
    $COMPOSE_CMD build --no-cache
  else
    $COMPOSE_CMD build --no-cache "$service"
  fi
}

compose_db_psql() {
  $COMPOSE_CMD exec db psql -U postgres -d fluent
}

# ── Runtime dispatch helpers ───────────────────────────────────────────────────

exec_ai() {
  if [ "$RUNTIME_MODE" = "podman-pod" ]; then
    podman_exec_ai "$@"
  else
    compose_exec_ai "$@"
  fi
}

# ── Runtime mode display ──────────────────────────────────────────────────────

echo "Runtime mode: $RUNTIME_MODE"
if [ "$RUNTIME_MODE" = "podman-pod" ]; then
  echo "Using native Podman pods"
else
  echo "Using Docker Compose (${COMPOSE_CMD})"
fi
echo ""

# ── Commands ──────────────────────────────────────────────────────────────────

cmd="${1:-help}"
shift || true

case "$cmd" in
  up)
    if [ "$RUNTIME_MODE" = "podman-pod" ]; then
      podman_up "${1:-all}"
    else
      compose_up "${1:-}"
    fi
    ;;

  down)
    if [ "$RUNTIME_MODE" = "podman-pod" ]; then
      podman_down "${1:-all}"
    else
      compose_down "${1:-}"
    fi
    ;;

  restart)
    if [ "$RUNTIME_MODE" = "podman-pod" ]; then
      podman_restart "${1:-all}"
    else
      compose_restart "${1:-}"
    fi
    ;;

  logs)
    if [ "$RUNTIME_MODE" = "podman-pod" ]; then
      podman_logs "${1:-}"
    else
      compose_logs "$@"
    fi
    ;;

  status)
    if [ "$RUNTIME_MODE" = "podman-pod" ]; then
      podman_status
    else
      compose_status
    fi
    ;;

  shell)
    if [ "$RUNTIME_MODE" = "podman-pod" ]; then
      podman_shell "${1:-ai}"
    else
      compose_shell "${1:-ai}"
    fi
    ;;

  # ── Development commands ───────────────────────────────────────────────────

  test)
    exec_ai uv run pytest tests/ -v "$@"
    ;;

  lint)
    exec_ai uv run ruff check "$@"
    ;;

  lint:fix)
    exec_ai uv run ruff check --fix "$@"
    ;;

  format)
    exec_ai uv run ruff format "$@"
    ;;

  format:check)
    exec_ai uv run ruff format --check "$@"
    ;;

  typecheck)
    exec_ai uv run mypy src "$@"
    ;;

  run)
    exec_ai uv run "$@"
    ;;

  # ── Database commands ──────────────────────────────────────────────────────

  db:migrate)
    echo_running "Running fluent-ai migrations..."
    echo "  (no migrations configured yet)"
    ;;

  db:seed)
    echo_running "Running fluent-ai seeds..."
    echo "  (no seeds configured yet)"
    ;;

  db:psql)
    if [ "$RUNTIME_MODE" = "podman-pod" ]; then
      podman_db_psql
    else
      compose_db_psql
    fi
    ;;

  # ── Lifecycle commands ─────────────────────────────────────────────────────

  clean)
    echo_running "This will stop and remove containers$([ "${1:-all}" = "all" ] && echo " and volumes" || true)."
    read -rp "Continue? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
      if [ "$RUNTIME_MODE" = "podman-pod" ]; then
        podman_clean "${1:-all}"
      else
        compose_clean "${1:-all}"
      fi
    else
      echo "Aborted."
    fi
    ;;

  fresh)
    echo_running "This will destroy ALL containers, volumes, and images."
    read -rp "Continue? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
      if [ "$RUNTIME_MODE" = "podman-pod" ]; then
        podman_fresh
      else
        compose_fresh
      fi
      echo ""
      echo_success "Clean slate. Run './fai.sh up' to rebuild and start everything."
    else
      echo "Aborted."
    fi
    ;;

  build)
    if [ "$RUNTIME_MODE" = "podman-pod" ]; then
      podman_build "${1:-ai}"
    else
      compose_build "${1:-}"
    fi
    ;;

  setup)
    if [[ ! -f .env ]]; then
      if [[ -f .env.example ]]; then
        cp .env.example .env
        echo "Created .env from .env.example"
      else
        touch .env
        echo "Created empty .env file"
      fi
    else
      echo ".env already exists, skipping."
    fi
    echo "Remember to fill in credentials in .env (API keys, etc.)"
    ;;

  help|*)
    cat <<'USAGE'
Usage: ./fai.sh <command> [service] [args]

Operating modes:
  Standalone  ./fai.sh up          — own DB on 5433 + AI service (safe alongside platform)
  Service     ./fai.sh up ai       — AI only; point DATABASE_URL at an existing DB
  Ecosystem   ./fluent.sh up       — platform orchestrator owns the shared DB on 5432

Services: db | ai | (omit for all)

Container management:
  up [service]           Start services (default: all — DB on 5433, then AI)
  down [service]         Stop and remove services (default: all)
  restart [service]      Restart services (default: all)
  logs [service]         Tail logs (default: all)
  status                 Show container/pod status
  shell [service]        Open a shell (default: ai; db opens psql)

Development (runs in AI container):
  test                   Run pytest test suite
  lint                   Run ruff linter
  lint:fix               Run ruff linter with auto-fix
  format                 Format code with ruff
  format:check           Check formatting with ruff
  typecheck              Run mypy type checking
  run <command>          Run a uv command inside the AI container

Database:
  db:migrate             Run AI schema migrations (TODO)
  db:seed                Run AI seeds (TODO)
  db:psql                Open psql session

Lifecycle:
  clean [service]        Remove containers and volumes (default: all)
  fresh                  Nuke everything: containers, volumes, and images
  build [service]        Rebuild images without cache
  setup                  Create .env from .env.example if missing

Environment variables:
  DB_PORT                Standalone DB host port (default: 5433; use 5432 for platform DB)
  AI_PORT                AI service host port (default: 8200)
  DATABASE_URL           Override DB connection (set in .env to use platform DB)
USAGE
    ;;
esac
