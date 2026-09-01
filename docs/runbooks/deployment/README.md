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

There is no automatic path to production, and no path to production that does
not pass through QA.

- [Standard release](prod-release.md) — the happy path
- [Rollback](prod-rollback.md) — put a previous build back
- [Emergency hotfix](prod-emergency-hotfix.md) — production is down

## How the QA gate works

`Deploy to QA` finishes by copying the image manifest to a second tag,
`qa-<commit>`. `Promote to Production` refuses any commit that has no such tag,
and re-checks that `qa-<commit>` and `sha-<commit>` are the same digest.

The gate deliberately does **not** read the GitHub deployments API. A
deployment's recorded `sha` is the sha of the workflow *run*, not of whatever
that run deployed — deploying an older commit to QA from a run dispatched
against `main` would file the deployment under main's head and the check would
match the wrong commit. An image tag attaches the evidence to the artifact
being promoted, so the mismatch cannot occur.

`skip_qa_check` exists for the case where production is down hard and even a QA
pass is too slow. It logs a warning naming the actor, and production's reviewer
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
