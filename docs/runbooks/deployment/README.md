# Deployment Runbooks

`fluent-ai` ships a container image. Every commit merged to `main` is built
**once** as `ghcr.io/eten-tech-foundation/fluent-ai:sha-<commit>`; QA and
production then deploy that same image. Production does not rebuild what QA
tested — it runs the identical bits.

Deployments are identified by **commit SHA**, not by tag. `/health` reports the
commit it is running, which is how each runbook below verifies its work.

## The four routes

| Route | Trigger | Goes to |
|---|---|---|
| **Build, Migrate & Deploy (Dev)** | automatic, on merge to `main` | dev |
| **Deploy to QA** | manual, takes a SHA (blank = head of `main`) | QA |
| **Promote to Production** | manual, takes a SHA | production, after approval |

There is no automatic path to production. Normal promotion requires a
successful QA deploy of the same commit; `skip_qa_check` is the one documented
exception, and it is covered under [the QA gate](#how-the-qa-gate-works) below.

- [Standard release](prod-release.md) — the happy path
- [Rollback](prod-rollback.md) — put a previous build back
- [Emergency hotfix](prod-emergency-hotfix.md) — production is down

## How the QA gate works

Both gates resolve `sha-<commit>` to a **digest** and deploy `image@sha256:…`,
never the tag. A tag is a mutable pointer, so before accepting a digest each
gate verifies the signed SLSA provenance attestation that the build pushes
alongside the image, and requires it to name this repository's build workflow
and the commit being deployed. That is what binds digest to commit; `/health`
cannot, because its `commit` is a value the deploy workflow injects.

On top of that, `Deploy to QA` finishes by retagging the deployed digest as
`qa-<commit>`. `Promote to Production` refuses any commit that has no such tag,
and re-checks that `qa-<commit>` and `sha-<commit>` resolve to the same digest.

The gate deliberately does **not** read the GitHub deployments API. A
deployment's recorded `sha` is the sha of the workflow *run*, not of whatever
that run deployed — deploying an older commit to QA from a run dispatched
against `main` would file the deployment under main's head and the check would
match the wrong commit. An image tag attaches the evidence to the artifact
being promoted, so the mismatch cannot occur.

`skip_qa_check` waives only the QA evidence. The commit must still be on
`main`, and its image must still carry valid provenance for that commit — the
bypass is for skipping a test cycle, never for shipping unattested content.

It exists for the case where production is down hard and even a QA pass is too
slow. It logs a warning naming the actor, and production's reviewer
approval still applies. Treat every use as something to raise at the incident
review.

## Required GitHub configuration

These workflows will run green and gate nothing until this is in place.

1. **A `qa` Environment**, with the same secret *names* as `development` and
   `production` (see below) and its own values, pointing at the `fluent-ai-qa`
   Web App and the QA database.
2. **Required reviewers on the `production` Environment.** It has
   `protection_rules: []` today. The pause before a production deploy *is* this
   rule; without it, `Promote to Production` deploys immediately.

Each of `development`, `qa` and `production` supplies, under these exact names:
`DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, `AZURE_CREDENTIALS`,
`AZURE_RESOURCE_GROUP`, `GHCR_USERNAME`, `GHCR_PAT`, `SECRET_KEY`,
`API_SERVICE_KEY`, `API_BASE_URL`, `ADMIN_API_KEY_HASH`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GOOGLE_AI_API_KEY`.

Do not reintroduce `_DEV`/`_QA`/`_PROD` suffixes — the environment is the scope,
and suffixed names are what let the three deploy jobs drift apart in the first
place.

> [!NOTE]
> `AZUREAPPSERVICE_PUBLISHPROFILE_*` is no longer used. Deploys authenticate
> with `AZURE_CREDENTIALS`, the same service principal that already reconfigures
> the Web App. The three publish-profile secrets can be deleted.

> [!NOTE]
> The `DEV_HEALTH_URL` / `PROD_HEALTH_URL` environment **variables** are no
> longer used either. The health check reads the URL from the deploy's own
> `webapp-url` output, so a new environment needs no health variable and no
> hostname is ever guessed — these apps have Azure unique default hostnames
> (`fluent-ai-dev-cucbe2d8hcbsctfq.westeurope-01…`), not `<app>.azurewebsites.net`.
> Set a `HEALTH_URL` variable on an environment only to override for a custom
> domain; with or without a trailing `/health` both work.
