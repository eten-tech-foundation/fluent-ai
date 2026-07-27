# CalVer Versioning + Tag-Based Deploys — Summary

## Problem

`main` is the default branch. Merging a PR builds a container image and deploys it to **dev** automatically; deploying to **prod** is a manual `workflow_dispatch` on `post-merge-deploy.yml` that runs against whatever commit is on `main` HEAD at the moment someone clicks the button.

Once a release enters its QA cycle, any PR that merges to `main` before someone dispatches the prod deploy either gets silently swept into that prod deploy unQA'd, or the team has to stop merging until the dispatch happens. Neither is acceptable.

A `develop`-as-default-branch alternative was considered and rejected: it introduces a second long-lived branch that drifts from `main`, requiring a manual "merge main back into develop" step after every hotfix that's easy to forget — recreating the exact "develop is behind by one commit" problem it was meant to solve.

## Recommendation: tag-based deploys

Keep `main` as the single trunk everyone merges into continuously — no new long-lived branch. Instead of prod deploying from whatever `main` HEAD happens to be, prod deploys from an explicit, immutable **git tag** cut on demand. The tag is what QA verifies; it doesn't move if someone merges to `main` afterward.

fluent-ai already builds an immutable, content-addressed artifact for every push — the `sha-<commit>` image tag pushed to GHCR in `post-merge-deploy.yml`. The tag-based approach extends that same idea one step further: instead of a mutable `dev`/`prod` image tag decided by a manual dropdown, the release tag itself becomes the image tag that gets deployed to prod.

## CalVer format

`YY.MM.SERIAL` — e.g. `26.07.3` is the 3rd release cut in July 2026. `SERIAL` resets implicitly each month (derived by scanning existing git tags for that `YY.MM` prefix, not stored anywhere separately).

## What changes

| Component | Change |
|---|---|
| `pre-merge.yml` | No change. Still gates every PR into `main` (ruff, mypy, pytest). |
| `post-merge-deploy.yml` | Dev path (push to `main`) unchanged: builds `sha-<sha>` + `dev` image, deploys to `fluent-ai-dev`. Prod path switches from manual `workflow_dispatch` to `push: tags: 'v*.*.*'` — the build job additionally tags the image with the release version and `prod`, and `deploy-prod` deploys that versioned image instead of a bare sha. |
| New `cut-release.yml` workflow | Manually triggered when the team is ready to start a QA cycle. Computes the next `YY.MM.SERIAL` git tag and pushes it — the one new step in the process. |
| `pyproject.toml` version | Optionally stamped from the tag at build time via `uv version`, so the running container can report its own version (e.g. from `/health`). |

## How this solves the blocking problem

- Engineers keep merging PRs to `main` at any time — merging is never gated by an in-flight QA cycle.
- QA tests a specific tagged image (`ghcr.io/.../fluent-ai:v26.07.3`), not a moving `dev`/`prod` mutable tag, so nothing merged after the tag was cut can leak into that release.
- If QA finds a bug: the fix lands on `main` as a normal PR, gets cherry-picked onto a short-lived branch cut from the QA'd tag, and a new tag (`SERIAL` bumped) is cut and rebuilt for re-verification. No second long-lived branch, no drift bookkeeping.
- Rollback becomes "redeploy the previous version tag's image" rather than a git-history exercise.

See `versioning-calver-workflows.md` for the detailed workflow definitions and step-by-step command sequences for each scenario.
