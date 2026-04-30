#Requires -Version 5.1
param(
    [Parameter(Position = 0)]
    [string]$Command = "help",
    [Parameter(Position = 1)]
    [string]$Service = "",
    [Parameter(Position = 2, ValueFromRemainingArguments)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ── Runtime detection (prefer native Podman pods) ─────────────────────────────

$RuntimeMode = ""
$Runtime = ""
$ComposeCmd = ""

function Detect-Runtime {
    if (Get-Command podman -ErrorAction SilentlyContinue) {
        $script:RuntimeMode = "podman-pod"
        $script:Runtime = "podman"
        return
    }
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        $v2 = & docker compose version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $script:RuntimeMode = "docker-compose"
            $script:ComposeCmd = "docker compose"
            return
        }
        if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
            $script:RuntimeMode = "docker-compose"
            $script:ComposeCmd = "docker-compose"
            return
        }
    }
    Write-Error @"
No container runtime found. Install one of:
  - Podman (native pods)
  - Docker Desktop (includes docker compose V2)
  - Docker Engine + docker-compose
"@
    exit 1
}

Detect-Runtime

# ── Color helpers ─────────────────────────────────────────────────────────────

function Write-Running([string]$msg) { Write-Host ">>> $msg" -ForegroundColor Yellow }
function Write-Success([string]$msg) { Write-Host ">>> $msg" -ForegroundColor Green }
function Write-Err([string]$msg)     { Write-Host ">>> $msg" -ForegroundColor Red }

# ── Podman pod configuration ──────────────────────────────────────────────────

$PodName = "fluent-ai"
# 5433 avoids conflict with the platform orchestrator's shared DB on 5432.
# Use DB_PORT=5432 (or set DATABASE_URL in .env) to connect to the platform DB instead.
$DbPort  = if ($env:DB_PORT)  { $env:DB_PORT }  else { "5433" }
$AiPort  = if ($env:AI_PORT)  { $env:AI_PORT }  else { "8200" }

# ── Podman helpers ────────────────────────────────────────────────────────────

function Invoke-Compose([string[]]$ComposeArgs) {
    if ($ComposeCmd -eq "docker compose") {
        & docker compose @ComposeArgs
    } else {
        & $ComposeCmd @ComposeArgs
    }
}

function Pod-Exists {
    & $Runtime pod exists $PodName 2>$null
    return $LASTEXITCODE -eq 0
}

function Container-Exists([string]$name) {
    & $Runtime container exists $name 2>$null
    return $LASTEXITCODE -eq 0
}

function Container-Running([string]$name) {
    $running = & $Runtime ps --format "{{.Names}}" 2>$null
    return $running -contains $name
}

function Pod-Create {
    if (Pod-Exists) {
        Write-Success "Pod $PodName already exists"
        return
    }
    Write-Running "Creating pod $PodName..."
    & $Runtime pod create `
        --name $PodName `
        --share "net,ipc,uts" `
        -p "${DbPort}:5432" `
        -p "${AiPort}:8200"
}

function Pod-Destroy {
    if (Pod-Exists) {
        Write-Running "Removing pod $PodName..."
        & $Runtime pod rm $PodName -f
    }
}

function Create-Volumes {
    Write-Running "Creating volumes..."
    & $Runtime volume create fluent-ai-pgdata 2>$null
}

function Wait-ForDb {
    Write-Running "Waiting for database to be ready..."
    while ($true) {
        & $Runtime exec fluent-ai-db pg_isready -U postgres -d fluent 2>$null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 2
    }
    Write-Success "Database is ready"
}

function Start-DbContainer {
    if (Container-Exists "fluent-ai-db") {
        Write-Success "Database container already exists"
        return
    }
    Write-Running "Starting database container..."
    & $Runtime run -d `
        --name fluent-ai-db `
        --pod $PodName `
        -e POSTGRES_USER=postgres `
        -e POSTGRES_PASSWORD=postgres `
        -e POSTGRES_DB=fluent `
        -v fluent-ai-pgdata:/var/lib/postgresql/data `
        -v "${ScriptDir}\db\init:/docker-entrypoint-initdb.d" `
        --health-cmd "pg_isready -U postgres -d fluent" `
        --health-interval 5s `
        --health-timeout 5s `
        --health-retries 5 `
        docker.io/postgres:16-alpine
    Write-Success "Database container started"
}

function Start-AiContainer {
    if (Container-Exists "fluent-ai-ai") {
        Write-Success "AI container already exists"
        return
    }
    Write-Running "Building AI image..."
    & $Runtime build -t fluent-ai $ScriptDir -f Dockerfile.dev

    $envFlags = @(
        "-e", "DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/fluent",
        "-e", "ENVIRONMENT=development",
        "-e", "DEBUG=true",
        "-e", "UV_CACHE_DIR=/app/.cache/uv"
    )
    if (Test-Path "$ScriptDir\.env") {
        $envFlags += "--env-file", "$ScriptDir\.env"
    }

    Write-Running "Starting AI container..."
    $runArgs = @(
        "run", "-d",
        "--name", "fluent-ai-ai",
        "--pod", $PodName
    ) + $envFlags + @(
        "-v", "${ScriptDir}\src:/app/src:ro",
        "-v", "${ScriptDir}\tests:/app/tests:ro",
        "-v", "${ScriptDir}\pyproject.toml:/app/pyproject.toml:ro",
        "-v", "${ScriptDir}\uv.lock:/app/uv.lock:ro",
        "-v", "${ScriptDir}\docker-entrypoint.sh:/app/docker-entrypoint.sh:ro",
        "--tmpfs", "/tmp:nosuid,size=64m",
        "--tmpfs", "/app/.cache:noexec,nosuid,size=128m",
        "--security-opt", "no-new-privileges:true",
        "--cap-drop", "ALL",
        "--user", "1001:1001",
        "--read-only",
        "fluent-ai"
    )
    & $Runtime @runArgs
    Write-Success "AI container started"
}

# ── Podman command functions ───────────────────────────────────────────────────

function Podman-Up([string]$svc = "all") {
    switch ($svc) {
        "all" {
            Create-Volumes
            Pod-Create
            Start-DbContainer
            Wait-ForDb
            Start-AiContainer
            Write-Success "All services started!"
        }
        "db" {
            Create-Volumes
            Pod-Create
            Start-DbContainer
            Write-Success "Database started!"
        }
        "ai" {
            Pod-Create
            Start-AiContainer
            Write-Success "AI service started!"
        }
        default {
            Write-Err "Unknown service: $svc (use: db, ai, or omit for all)"
            exit 1
        }
    }
}

function Podman-Down([string]$svc = "all") {
    if ($svc -eq "all") {
        Pod-Destroy
        Write-Success "All services stopped."
    } else {
        Write-Running "Stopping $svc..."
        & $Runtime rm -f "fluent-ai-$svc" 2>$null
        Write-Success "$svc stopped."
    }
}

function Podman-Restart([string]$svc = "all") {
    if ($svc -eq "all") {
        Pod-Destroy
        Podman-Up "all"
    } else {
        Write-Running "Restarting $svc..."
        & $Runtime rm -f "fluent-ai-$svc" 2>$null
        switch ($svc) {
            "db"  { Start-DbContainer }
            "ai"  { Start-AiContainer }
            default { Write-Err "Unknown service: $svc"; exit 1 }
        }
        Write-Success "Restarted $svc"
    }
}

function Podman-ExecAi([string[]]$cmdArgs) {
    if (-not (Container-Running "fluent-ai-ai")) {
        Write-Err "AI container is not running. Run '.\fai.ps1 up ai' first."
        exit 1
    }
    & $Runtime exec fluent-ai-ai @cmdArgs
}

function Podman-Clean([string]$svc = "all") {
    if ($svc -eq "all") {
        Pod-Destroy
        & $Runtime volume rm fluent-ai-pgdata 2>$null
        Write-Success "All containers and volumes removed."
    } else {
        & $Runtime rm -f "fluent-ai-$svc" 2>$null
        Write-Success "$svc container removed."
    }
}

function Podman-Fresh {
    Pod-Destroy
    & $Runtime volume rm fluent-ai-pgdata 2>$null
    & $Runtime rmi -f fluent-ai 2>$null
    Write-Success "Removed all containers, volumes, and images."
}

function Podman-Build([string]$svc = "ai") {
    if ($svc -eq "ai" -or $svc -eq "all") {
        Write-Running "Building AI image..."
        & $Runtime build -t fluent-ai $ScriptDir -f Dockerfile.dev
        Write-Success "AI image built."
    } else {
        Write-Err "Unknown buildable service: $svc (only 'ai' has a custom image)"
        exit 1
    }
}

# ── Docker Compose command functions ──────────────────────────────────────────

function Compose-Up([string]$svc = "") {
    if ($svc -eq "" -or $svc -eq "all") {
        # Start everything — compose resolves depends_on and waits for DB health
        Invoke-Compose @("up", "-d", "--build")
    } else {
        # Start only the requested service; the caller is responsible for any deps
        Invoke-Compose @("up", "-d", "--build", "--no-deps", $svc)
    }
}

function Compose-Down([string]$svc = "") {
    if ($svc -eq "" -or $svc -eq "all") {
        Invoke-Compose @("down")
    } else {
        Invoke-Compose @("rm", "-sf", $svc)
    }
}

function Compose-Restart([string]$svc = "") {
    if ($svc -eq "" -or $svc -eq "all") {
        Invoke-Compose @("restart")
    } else {
        Invoke-Compose @("restart", $svc)
    }
}

function Compose-ExecAi([string[]]$cmdArgs) {
    Invoke-Compose (@("exec", "ai") + $cmdArgs)
}

function Compose-Clean([string]$svc = "all") {
    if ($svc -eq "all") {
        Invoke-Compose @("down", "-v")
        Write-Success "All containers and volumes removed."
    } else {
        Invoke-Compose @("rm", "-sf", $svc)
        Write-Success "$svc container removed."
    }
}

function Compose-Fresh {
    Invoke-Compose @("down", "-v", "--rmi", "local", "--remove-orphans")
    Write-Success "Removed all containers, volumes, and images."
}

function Compose-Build([string]$svc = "") {
    if ($svc -eq "" -or $svc -eq "all") {
        Invoke-Compose @("build", "--no-cache")
    } else {
        Invoke-Compose @("build", "--no-cache", $svc)
    }
}

# ── Exec-AI dispatch ──────────────────────────────────────────────────────────

function Exec-Ai([string[]]$cmdArgs) {
    if ($RuntimeMode -eq "podman-pod") {
        Podman-ExecAi $cmdArgs
    } else {
        Compose-ExecAi $cmdArgs
    }
}

# ── Runtime mode display ──────────────────────────────────────────────────────

Write-Host "Runtime mode: $RuntimeMode"
if ($RuntimeMode -eq "podman-pod") {
    Write-Host "Using native Podman pods"
} else {
    Write-Host "Using Docker Compose ($ComposeCmd)"
}
Write-Host ""

# ── Commands ──────────────────────────────────────────────────────────────────

$svcArg = if ($Service) { $Service } else { "" }

switch ($Command) {
    "up" {
        if ($RuntimeMode -eq "podman-pod") {
            Podman-Up ($svcArg -or "all")
        } else {
            Compose-Up $svcArg
        }
    }
    "down" {
        if ($RuntimeMode -eq "podman-pod") {
            Podman-Down ($svcArg -or "all")
        } else {
            Compose-Down $svcArg
        }
    }
    "restart" {
        if ($RuntimeMode -eq "podman-pod") {
            Podman-Restart ($svcArg -or "all")
        } else {
            Compose-Restart $svcArg
        }
    }
    "logs" {
        if ($RuntimeMode -eq "podman-pod") {
            if ($svcArg) {
                # Route through pod logs --container to avoid direct name-resolution
                # bugs in some podman builds where 'podman logs <hyphenated-name>' fails.
                & $Runtime pod logs --container "fluent-ai-$svcArg" -f $PodName
            } else {
                & $Runtime pod logs -f $PodName
            }
        } else {
            if ($svcArg) {
                Invoke-Compose @("logs", "-f", $svcArg)
            } else {
                Invoke-Compose @("logs", "-f")
            }
        }
    }
    "status" {
        if ($RuntimeMode -eq "podman-pod") {
            & $Runtime pod ps
            if (Pod-Exists) {
                Write-Host ""
                Write-Host "Containers in pod ${PodName} (all states):"
                & $Runtime ps -a --filter "pod=$PodName"
            }
        } else {
            Invoke-Compose @("ps")
        }
    }
    "shell" {
        $target = if ($svcArg) { $svcArg } else { "ai" }
        if ($RuntimeMode -eq "podman-pod") {
            if ($target -eq "db") {
                & $Runtime exec -it fluent-ai-db psql -U postgres -d fluent
            } else {
                & $Runtime exec -it "fluent-ai-$target" sh
            }
        } else {
            if ($target -eq "db") {
                Invoke-Compose @("exec", "db", "psql", "-U", "postgres", "-d", "fluent")
            } else {
                Invoke-Compose @("exec", $target, "sh")
            }
        }
    }

    # ── Development commands ─────────────────────────────────────────────────

    "test"          { Exec-Ai @("uv", "run", "pytest", "tests/", "-v") + $Args }
    "lint"          { Exec-Ai @("uv", "run", "ruff", "check") + $Args }
    "lint:fix"      { Exec-Ai @("uv", "run", "ruff", "check", "--fix") + $Args }
    "format"        { Exec-Ai @("uv", "run", "ruff", "format") + $Args }
    "format:check"  { Exec-Ai @("uv", "run", "ruff", "format", "--check") + $Args }
    "typecheck"     { Exec-Ai @("uv", "run", "mypy", "src") + $Args }
    "run"           { Exec-Ai (@("uv", "run") + $Args) }

    # ── Database commands ────────────────────────────────────────────────────

    "db:migrate" {
        Write-Running "Running fluent-ai migrations..."
        Write-Host "  (no migrations configured yet)"
    }
    "db:seed" {
        Write-Running "Running fluent-ai seeds..."
        Write-Host "  (no seeds configured yet)"
    }
    "db:psql" {
        if ($RuntimeMode -eq "podman-pod") {
            & $Runtime exec -it fluent-ai-db psql -U postgres -d fluent
        } else {
            Invoke-Compose @("exec", "db", "psql", "-U", "postgres", "-d", "fluent")
        }
    }

    # ── Lifecycle commands ───────────────────────────────────────────────────

    "clean" {
        $target = if ($svcArg) { $svcArg } else { "all" }
        $volNote = if ($target -eq "all") { " and volumes" } else { "" }
        Write-Host "This will stop and remove $target containers$volNote."
        $confirm = Read-Host "Continue? [y/N]"
        if ($confirm -match "^[Yy]$") {
            if ($RuntimeMode -eq "podman-pod") {
                Podman-Clean $target
            } else {
                Compose-Clean $target
            }
        } else {
            Write-Host "Aborted."
        }
    }
    "fresh" {
        Write-Host "This will destroy ALL containers, volumes, and images."
        $confirm = Read-Host "Continue? [y/N]"
        if ($confirm -match "^[Yy]$") {
            if ($RuntimeMode -eq "podman-pod") {
                Podman-Fresh
            } else {
                Compose-Fresh
            }
            Write-Host ""
            Write-Success "Clean slate. Run '.\fai.ps1 up' to rebuild and start everything."
        } else {
            Write-Host "Aborted."
        }
    }
    "build" {
        if ($RuntimeMode -eq "podman-pod") {
            Podman-Build ($svcArg -or "ai")
        } else {
            Compose-Build $svcArg
        }
    }
    "setup" {
        if (-not (Test-Path .env)) {
            if (Test-Path .env.example) {
                Copy-Item .env.example .env
                Write-Host "Created .env from .env.example"
            } else {
                New-Item .env -ItemType File | Out-Null
                Write-Host "Created empty .env file"
            }
        } else {
            Write-Host ".env already exists, skipping."
        }
        Write-Host "Remember to fill in credentials in .env (API keys, etc.)"
    }
    default {
        @"
Usage: .\fai.ps1 <command> [service] [args]

Operating modes:
  Standalone  .\fai.ps1 up         -- own DB on 5433 + AI service (safe alongside platform)
  Service     .\fai.ps1 up ai      -- AI only; point DATABASE_URL at an existing DB
  Ecosystem   .\fluent.ps1 up      -- platform orchestrator owns the shared DB on 5432

Services: db | ai | (omit for all)

Container management:
  up [service]           Start services (default: all -- DB on 5433, then AI)
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
"@
    }
}
