# fluent-ai Deployment to Azure App Service — Design

**Date:** 2026-07-14

## Overview

`fluent-ai` has never been deployed anywhere and has no `.github/workflows` directory.
This spec designs CI/CD to deploy it to Azure App Service (Web App for Containers),
closely mirroring the pattern already proven in `fluent-api/.github/workflows/`
(`pre-merge.yml`, `post-merge-deploy.yml`, `pr-closed.yml`).

**Relationship to the existing ACA plan:** `fluent-platform/docs/2026-07-14-fluent-ai-deployment-plan.md`
already designs a deployment to Azure Container Apps as part of a platform-wide
GitOps move (shared Bicep IaC, Key Vault, ACA Environment). That plan is retained
for a later platform-wide migration. This spec is a separate, near-term path: get
`fluent-ai` running in production now, using App Service and the same
lightweight, per-repo CI/CD pattern `fluent-api` already uses — no shared IaC, no
Key Vault, no ACA.

## Architecture

```
GitHub (fluent-ai)                              Azure
┌───────────────────────┐
│ pre-merge.yml          │  PR → lint, format check, typecheck, test
│ post-merge-deploy.yml  │  push main        → build, migrate, deploy dev
│                        │  workflow_dispatch → build, migrate, deploy dev|prod
│ pr-closed.yml          │  merged PR → delete branch
│ dependabot.yml         │  daily github-actions updates
└───────────┬────────────┘
            │ docker build (production Dockerfile)
            ▼
   ghcr.io/eten-tech-foundation/fluent-ai
      :sha-<gitsha>   (immutable, what App Service actually runs)
      :dev / :prod    (mutable pointer, human-readable)
            │
            ▼
   App Service (Web App for Containers, Linux)
     fluent-ai-dev                fluent-ai-prod
     pulls image from GHCR        pulls image from GHCR
     app settings = secrets       app settings = secrets
```

## 1. Image Build & Registry

Registry: GitHub Container Registry (`ghcr.io/eten-tech-foundation/fluent-ai`).

- Free for public repos, no extra auth in GitHub Actions beyond `GITHUB_TOKEN`
- Same registry choice as the existing ACA plan, so nothing changes here if the
  platform-wide migration happens later
- Tagging strategy:
  - `sha-<git-sha>` — immutable, what App Service runs
  - `dev` — mutable, points at latest dev deployment
  - `prod` — mutable, points at latest prod deployment

The production `Dockerfile` (already in the repo) is used as-is. No new Dockerfile
is needed.

## 2. GitHub Actions Workflows

### `pre-merge.yml` (new)

Mirrors `fluent-api/.github/workflows/pre-merge.yml`, adapted for Python/uv:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    branches: [main]

jobs:
  validate:
    if: ${{ !github.event.pull_request.draft }}
    steps:
      - checkout
      - set up uv / Python 3.14
      - uv sync --frozen
      - uv run ruff check
      - uv run ruff format --check
      - uv run mypy
      - uv run pytest
```

### `post-merge-deploy.yml` (new)

Mirrors `fluent-api/.github/workflows/post-merge-deploy.yml`'s job structure
(`build` → `migrate-*` → `deploy-*`), swapping the npm/zip steps for
docker build + push, and `azure/webapps-deploy` targeting a container image
instead of a package directory.

```yaml
on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      environment:
        description: Environment to deploy to
        required: true
        default: dev
        type: choice
        options: [dev, prod]

jobs:
  build:
    steps:
      - checkout
      - docker build (production Dockerfile)
      - docker push ghcr.io/.../fluent-ai:sha-<sha>
      - docker tag/push :dev (or :prod, depending on trigger)

  migrate-dev:
    needs: build
    if: push to main, or workflow_dispatch with environment=dev
    environment: Development
    env:
      MIGRATIONS_DATABASE_URL: ${{ secrets.MIGRATIONS_DATABASE_URL }}
    steps:
      - uv sync --frozen --no-dev
      - uv run alembic upgrade head

  migrate-prod:
    needs: build
    if: workflow_dispatch with environment=prod
    environment: Production
    env:
      MIGRATIONS_DATABASE_URL: ${{ secrets.MIGRATIONS_DATABASE_URL }}
    steps: (same as migrate-dev)

  deploy-dev:
    needs: [build, migrate-dev]
    if: push to main, or workflow_dispatch with environment=dev
    environment:
      name: Development
      url: ${{ steps.deploy.outputs.webapp-url }}
    steps:
      - az webapp config appsettings set (from Development secrets)
      - azure/webapps-deploy@v3, images: ghcr.io/.../fluent-ai:sha-<sha>
        app-name: fluent-ai-dev
        publish-profile: ${{ secrets.AZUREAPPSERVICE_PUBLISHPROFILE_DEV }}
      - verify: curl loop against /health (same retry pattern as fluent-api)

  deploy-prod:
    needs: [build, migrate-prod]
    if: workflow_dispatch with environment=prod
    environment:
      name: Production
      url: ${{ steps.deploy.outputs.webapp-url }}
    steps: (same shape as deploy-dev, targeting fluent-ai-prod)
```

**Why separate migrate/deploy jobs per environment:** exactly fluent-api's
reasoning — migrations run once from a single CI runner, before the new image is
live; if migration fails, the deploy job never starts.

### `pr-closed.yml` and `dependabot.yml` (new)

Copied over unchanged from `fluent-api` — auto-delete merged branches, daily
github-actions dependency updates.

## 3. Deployment Mechanism: Web App for Containers

App Service is configured as "Web App for Containers" (Linux), pointed at the
GHCR image rather than doing an Oryx/pip build from source. This reuses the
existing production `Dockerfile` unchanged and avoids Python build quirks on
App Service's native runtime.

Deploy step uses `azure/webapps-deploy@v3` with an `images:` input (or
equivalently `az webapp config container set --docker-custom-image-name`)
against `fluent-ai-dev` / `fluent-ai-prod`.

## 4. Secrets Management

No Key Vault — mirrors fluent-api's simpler model.

**Runtime secrets** (GitHub Environment secrets, applied as App Service app
settings on deploy via `az webapp config appsettings set` or the deploy step):

- `DATABASE_URL`
- `SECRET_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_AI_API_KEY`
- `API_SERVICE_KEY` (key fluent-ai presents when calling fluent-api)
- `ADMIN_API_KEY_HASH` (prod only)

**CI-only secrets** (GitHub Environment secrets, never touch the app):

- `AZUREAPPSERVICE_PUBLISHPROFILE_DEV` / `_PROD` — publish-profile auth, matching
  fluent-api's actual pattern (`AZUREAPPSERVICE_PUBLISHPROFILE_947D34B0D69C4986A7E211253893C796`
  for dev, `AZUREAPPSERVICE_PUBLISHPROFILE_PROD` for prod), not OIDC/service
  principal
- `MIGRATIONS_DATABASE_URL`
- `BOOTSTRAP_DATABASE_URL` (first-time DB provisioning only)

Two GitHub Environments are created: `Development` and `Production`, matching
fluent-api's environment names.

## 5. Database Migrations

**Critical, already noted in the ACA plan and still true here:** the production
`Dockerfile` runs `fastapi run` directly — it does not run migrations.
`docker-entrypoint.sh` (bootstrap/migrate/seed) is dev-only, used by
`Dockerfile.dev`.

Migrations run in CI, before deployment, exactly as fluent-api does:

```yaml
- name: Run Alembic migrations
  env:
    MIGRATIONS_DATABASE_URL: ${{ secrets.MIGRATIONS_DATABASE_URL }}
  run: |
    uv sync --frozen --no-dev
    uv run alembic upgrade head
```

If migration fails, the corresponding `deploy-*` job never runs.

**First-time DB setup** (once per environment, run manually):

```bash
BOOTSTRAP_DATABASE_URL="..." uv run python scripts/bootstrap.py
```

## 6. First-Time Infrastructure Provisioning

Nothing exists in Azure for `fluent-ai` yet. One-time manual setup (run in this
order, and re-run if resources are ever recreated):

1. Confirm the resource group / region / subscription fluent-api's App Service
   resources already live in — put fluent-ai's resources there for now, to keep
   the two services co-located operationally.
2. Create an App Service Plan (Linux, container-capable) if not reusing
   fluent-api's, plus two Web Apps: `fluent-ai-dev`, `fluent-ai-prod`, each
   configured for a custom container image (`az webapp create
   --deployment-container-image-name ...`).
3. Configure each Web App's container registry auth against GHCR (public image —
   likely no credentials needed, same as the ACA plan assumed).
4. Retrieve each Web App's publish profile and store as
   `AZUREAPPSERVICE_PUBLISHPROFILE_DEV` / `_PROD` in the matching GitHub
   Environment.
5. Populate `Development`/`Production` GitHub Environment secrets (§4).
6. Run `BOOTSTRAP_DATABASE_URL="..." uv run python scripts/bootstrap.py` once
   per environment against the managed Postgres instance.

## 7. Networking & Service Discovery

- `fluent-ai-dev` / `fluent-ai-prod` get public URLs:
  `https://fluent-ai-dev.azurewebsites.net`, `https://fluent-ai-prod.azurewebsites.net`
- `fluent-api` calls fluent-ai via these URLs (`FLUENT_AI_URL` on the fluent-api
  side)
- `fluent-ai` calls fluent-api via `API_BASE_URL`, authenticated with
  `API_SERVICE_KEY`

## 8. Rollback Strategy

- **Fast rollback:** re-run `post-merge-deploy.yml` via `workflow_dispatch`,
  redeploying the previous known-good `sha-<sha>` image tag.
- **DB rollback:** `alembic downgrade` run manually from CI if a migration needs
  reverting.

## 9. Pilot Rollout

Same staged approach as the ACA plan (§8 of that doc) applies regardless of
compute target:

1. **Dev pilot:** deploy to `fluent-ai-dev` only. Set `FLUENT_AI_URL` /
   `FLUENT_AI_KEY` in fluent-api's `Development` environment secrets.
   fluent-api's production deployment is untouched.
2. **Validate:** exercise AI-dependent routes and `ai-trigger.worker.ts` against
   the dev app — health probe, migrations, request/response contract, failure
   handling.
3. **Cutover to prod:** deploy `fluent-ai-prod`, then add `FLUENT_AI_URL` /
   `FLUENT_AI_KEY` to fluent-api's `Production` environment. Reversible by
   unsetting `FLUENT_AI_URL`.

## 10. Out of Scope (Deliberate Deferrals)

- **Staging environment** — dev/prod only, as in the ACA plan.
- **Key Vault / managed identity** — deferred to the platform-wide ACA
  migration, if it happens; App Settings are sufficient for this near-term path.
- **Shared IaC (Bicep)** — App Service config lives in `az` CLI calls inside the
  workflow, not committed infra-as-code, matching fluent-api's current setup.
- **ACA migration** — `fluent-platform/docs/2026-07-14-fluent-ai-deployment-plan.md`
  remains the reference for that later, platform-wide change.

## 11. Cost Estimate (monthly, low traffic)

App Service Basic/Standard tier (Linux, container) pricing depends on the plan
size chosen and whether it's shared with fluent-api's existing plan. If sharing
fluent-api's App Service Plan, marginal cost for `fluent-ai` may be close to $0;
if a new plan is provisioned, budget similarly to a small B1 instance
(~$13-15/mo per environment). Confirm against fluent-api's current plan/SKU
before finalizing.
