#Requires -Version 5.1
param(
    [Parameter(Position = 0)]
    [string]$Command = "help",
    [Parameter(Position = 1, ValueFromRemainingArguments)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"

# ── Runtime detection (prefer Podman) ──────────────────────────────────────────

function Get-ComposeCommand {
    if ((Get-Command podman -ErrorAction SilentlyContinue) -and (Get-Command podman-compose -ErrorAction SilentlyContinue)) {
        return "podman-compose"
    }
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        $v2 = & docker compose version 2>&1
        if ($LASTEXITCODE -eq 0) { return "docker compose" }
        if (Get-Command docker-compose -ErrorAction SilentlyContinue) { return "docker-compose" }
    }
    Write-Error @"
No container runtime found. Install one of:
  - Podman + podman-compose
  - Docker Desktop (includes docker compose V2)
  - Docker Engine + docker-compose
"@
    exit 1
}

$Compose = Get-ComposeCommand

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    if ($Compose -eq "docker compose") {
        & docker compose @ComposeArgs
    } else {
        & $Compose @ComposeArgs
    }
}

# ── Commands ───────────────────────────────────────────────────────────────────

switch ($Command) {
    "up" {
        Invoke-Compose @("up", "-d", "--build") + $Args
    }
    "down" {
        Invoke-Compose @("down") + $Args
    }
    "restart" {
        Invoke-Compose @("restart") + $Args
    }
    "logs" {
        Invoke-Compose @("logs", "-f") + $Args
    }
    "status" {
        Invoke-Compose @("ps") + $Args
    }
    "db:migrate" {
        Write-Host "Running fluent-ai migrations..."
        Write-Host "TODO: Add migration command when ai schema migrations are set up"
        # Invoke-Compose @("exec", "ai", "uv", "run", "alembic", "upgrade", "head")
    }
    "db:seed" {
        Write-Host "Running fluent-ai seeds..."
        Write-Host "TODO: Add seed command when ai seeds are created"
        # Invoke-Compose @("exec", "ai", "uv", "run", "python", "src/db/seeds/seed.py")
    }
    "db:psql" {
        Invoke-Compose @("exec", "db", "psql", "-U", "postgres", "-d", "fluent")
    }
    "shell" {
        $service = if ($Args.Count -gt 0) { $Args[0] } else { "ai" }
        if ($service -eq "db") {
            Invoke-Compose @("exec", "db", "psql", "-U", "postgres", "-d", "fluent")
        } else {
            Invoke-Compose @("exec", $service, "sh")
        }
    }
    "test" {
        Invoke-Compose @("exec", "ai", "uv", "run", "pytest") + $Args
    }
    "run" {
        Invoke-Compose @("exec", "ai", "uv", "run") + $Args
    }
    "clean" {
        Write-Host "This will remove all containers AND volumes (full DB reset)."
        $confirm = Read-Host "Continue? [y/N]"
        if ($confirm -match "^[Yy]$") {
            Invoke-Compose @("down", "-v")
            Remove-Item -Force -ErrorAction SilentlyContinue .db-initialized
        } else {
            Write-Host "Aborted."
        }
    }
    "build" {
        Invoke-Compose @("build", "--no-cache") + $Args
    }
    "setup" {
        if (-not (Test-Path .env)) {
            Copy-Item .env.example .env
            Write-Host "Created .env from .env.example"
        } else {
            Write-Host ".env already exists, skipping copy."
        }
        Write-Host "Remember to fill in API keys and other credentials in .env"
    }
    default {
        @"
Usage: .\fai.ps1 <command> [args]

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
  setup           Copy .env.example -> .env if missing
"@
    }
}
