@echo off
REM Fluent AI CLI - Windows wrapper for Docker/Podman

setlocal enabledelayedexpansion

cd /d "%~dp0"

REM Detect container runtime
where docker >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set RUNTIME=docker
    set COMPOSE=docker compose
    goto :found
)

where podman >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set RUNTIME=podman
    where podman-compose >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set COMPOSE=podman-compose
    ) else (
        set COMPOSE=podman compose
    )
    goto :found
)

echo Error: Neither docker nor podman found. Please install one.
exit /b 1

:found

REM Default environment
if "%FAI_ENV%"=="" (
    set ENV=dev
) else (
    set ENV=%FAI_ENV%
)
set LOCAL_DB=false

REM Parse options
:parse_options
if "%~1"=="--prod" (
    set ENV=prod
    shift
    goto :parse_options
)
if "%~1"=="--dev" (
    set ENV=dev
    shift
    goto :parse_options
)
if "%~1"=="--local-db" (
    set LOCAL_DB=true
    shift
    goto :parse_options
)

REM Set compose files based on environment
if "%ENV%"=="prod" (
    set COMPOSE_FILES=-f docker-compose.base.yml -f docker-compose.prod.yml
    set ENV_FILE=.env.prod
) else (
    set COMPOSE_FILES=-f docker-compose.base.yml -f docker-compose.dev.yml
    set ENV_FILE=.env.dev
)

REM Add profile for local database if requested
set PROFILE_ARG=
if "%LOCAL_DB%"=="true" (
    set PROFILE_ARG=--profile local-db
)

REM Use env file if it exists
set ENV_FILE_ARG=
if exist "%ENV_FILE%" (
    set ENV_FILE_ARG=--env-file %ENV_FILE%
)

REM Full compose command
set COMPOSE_CMD=%COMPOSE% %COMPOSE_FILES% %ENV_FILE_ARG% %PROFILE_ARG%

if "%~1"=="" goto :usage
if "%~1"=="start" goto :start
if "%~1"=="stop" goto :stop
if "%~1"=="restart" goto :restart
if "%~1"=="logs" goto :logs
if "%~1"=="build" goto :build
if "%~1"=="status" goto :status
if "%~1"=="shell" goto :shell
if "%~1"=="clean" goto :clean
goto :usage

:start
echo Starting Fluent AI (%ENV%)...
%COMPOSE_CMD% up -d --build
echo Fluent AI is running at http://localhost:8200
echo API docs available at http://localhost:8200/docs
goto :eof

:stop
echo Stopping Fluent AI...
%COMPOSE_CMD% down
goto :eof

:restart
echo Restarting Fluent AI...
%COMPOSE_CMD% restart
goto :eof

:logs
%COMPOSE_CMD% logs -f
goto :eof

:build
echo Building Fluent AI (%ENV%)...
%COMPOSE_CMD% build
goto :eof

:status
%COMPOSE_CMD% ps
goto :eof

:shell
%COMPOSE_CMD% exec app /bin/bash || %COMPOSE_CMD% exec app /bin/sh
goto :eof

:clean
echo Cleaning up Fluent AI containers, volumes, and images...
%COMPOSE_CMD% down -v --rmi local
goto :eof

:usage
echo Fluent AI CLI
echo.
echo Usage: fai [options] ^<command^>
echo.
echo Options:
echo   --dev         Use development environment (default)
echo   --prod        Use production environment
echo   --local-db    Include local PostgreSQL container
echo.
echo Commands:
echo   start         Start the application (builds if needed)
echo   stop          Stop the application
echo   restart       Restart the application
echo   logs          View application logs (follow mode)
echo   build         Build/rebuild the application image
echo   status        Show running containers
echo   shell         Open a shell in the app container
echo   clean         Stop and remove containers, volumes, and images
echo.
echo Examples:
echo   fai start                    # Dev mode with cloud DB
echo   fai --local-db start         # Dev mode with local PostgreSQL
echo   fai --prod start             # Production mode
echo.
echo Environment: %ENV% ^| Local DB: %LOCAL_DB% ^| Runtime: %RUNTIME%
goto :eof
