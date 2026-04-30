# GitOps Roadmap — Fluent Platform

**Date:** 2026-04-17

## Overview

A phased plan for moving from individually containerized services with local helper scripts
to a GitOps-style CI/CD pipeline where git is the source of truth for what runs in
production.

---

## Where We Are Now

- Individual services (`fluent-ai`, `fluent-platform`, likely more) each with local
  container tooling (`fai.sh`, `fluent.sh`)
- No CI, no container registry, no deployment pipeline
- Dev runs locally via scripts; deployment is manual

---

## Phase 1 — CI Foundation *(in progress)*

**Per service:** GitHub Actions runs lint, typecheck, tests on every PR.

**Effort:** Low. Replicate the same workflow for each service repo.

**Reference:** `docs/superpowers/specs/2026-04-17-basic-ci-design.md`

---

## Phase 2 — Image Publishing

**Per service:** On merge to `main`, CI builds the production image and pushes it to a
registry tagged with the git SHA and `latest`.

`ghcr.io` (GitHub Container Registry) is the natural default — zero cost for public repos,
tight GitHub Actions integration, no extra credentials complexity.

**What's needed:**
- Add a `publish` job to each CI workflow (runs after `quality` + `docker` pass)
- Choose a registry and create credentials (one-time per org)
- Decide on a tagging strategy (SHA, semver tags, `latest`)

**Effort:** Low per service once the pattern is established.

---

## Phase 3 — Deployment Manifests *(the GitOps pivot)*

This is where git becomes the source of truth for what runs in production. The desired
state ("production should be running `fluent-ai:abc1234`") lives in git. When that
declaration changes, something applies it.

**Two structural options:**

- **Manifests in each service repo** — simple, colocated with the code, works well for
  small teams
- **Separate infra repo** (e.g., `fluent-infra`) — single place to see all services and
  environments, better audit trail for "what changed in prod and when"

For a multi-service platform, a separate infra repo is the cleaner long-term choice.

**What's needed:**
- Choose a manifest format (see Phase 4)
- Decide on environments (`prod` only, or `staging` + `prod`)
- Decide: manifests in each service repo or a shared infra repo

---

## Phase 4 — CD Pipeline *(infrastructure decision gate)*

The deployment target determines the manifest format and CD mechanism:

| Target | Manifest format | CD mechanism | Complexity |
|---|---|---|---|
| VPS / VM | `compose.yaml` | GitHub Actions → SSH → `docker compose pull && up` | Low |
| Kubernetes | k8s YAML or Helm | ArgoCD or Flux watches the infra repo | Medium–High |
| PaaS (Fly.io, Render) | Platform-native | Platform webhooks or CLI in CI | Low |

For a team still deciding on infrastructure, **VPS + Compose** is the lowest-friction path
to true GitOps: git controls the compose file, a merge triggers a deploy, everything is
auditable. Kubernetes is more powerful but carries significantly more operational overhead.

---

## Phase 5 — Environment Promotion

Once staging and prod exist, promotion is: update the image tag in the staging manifest →
verify → update the image tag in the prod manifest.

With an infra repo this is a PR: the diff is the change, the approval is the review, the
merge is the deploy. That's the GitOps payoff.

---

## Key Decisions Required Before Phase 3+

| Decision | Options | Notes |
|---|---|---|
| Where does the code run? | VPS, Kubernetes, PaaS | VPS is the simplest starting point |
| How many environments? | prod only, staging + prod | Start with prod; add staging when needed |
| Infra repo? | Per-service or shared `fluent-infra` | Shared repo recommended for multi-service |

---

## What Can Be Done Now (Decision-Independent)

- Complete CI for `fluent-ai` *(in progress)*
- Replicate CI workflow for `fluent-platform` and other services
- Add image publishing (Phase 2) to each CI workflow

Phase 2 is the logical next increment and unblocks everything else regardless of
infrastructure decisions.
