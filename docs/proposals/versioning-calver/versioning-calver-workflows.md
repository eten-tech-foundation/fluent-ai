# CalVer Versioning + Tag-Based Deploys — Detailed Workflow Changes

See `versioning-calver-summary.md` for the problem statement and rationale. This document covers the concrete workflow file changes and the command sequence for each operational scenario, specific to fluent-ai's GHCR-image + Azure Web App container deploy pipeline.

## Tag format

```
v<YY>.<MM>.<SERIAL>
```

- `YY.MM` — two-digit year and month the release was cut, e.g. `26.07`.
- `SERIAL` — 1-indexed count of releases cut in that year/month, reset implicitly each month. Not stored in any file; derived by scanning existing tags matching `v<YY>.<MM>.*` and incrementing the highest found.

Examples: `v26.07.1`, `v26.07.2`, ... `v26.08.1` (resets in August).

## 1. New workflow: `cut-release.yml`

Add `.github/workflows/cut-release.yml`. Manually triggered — this is the "start a QA cycle" button.

```yaml
name: Cut release
on:
  workflow_dispatch: {}

jobs:
  tag:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          fetch-depth: 0   # need full tag history to compute the next serial
          persist-credentials: true

      - name: Compute CalVer tag
        id: version
        run: |
          YEAR_MONTH=$(date +'%y.%m')
          SERIAL=$(git tag -l "v${YEAR_MONTH}.*" | sed -E "s/^v${YEAR_MONTH}\.//" | sort -n | tail -1)
          SERIAL=${SERIAL:-0}
          NEXT=$((SERIAL + 1))
          TAG="v${YEAR_MONTH}.${NEXT}"
          echo "tag=$TAG" >> "$GITHUB_OUTPUT"
          echo "Computed tag: $TAG"

      - name: Tag and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git tag ${{ steps.version.outputs.tag }}
          git push origin ${{ steps.version.outputs.tag }}

      - name: Create GitHub release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ steps.version.outputs.tag }}
          generate_release_notes: true
```

Pushing the tag triggers `post-merge-deploy.yml`'s prod path (see below) via the `tags:` push trigger.

## 2. Change: `post-merge-deploy.yml` triggers

Current trigger:

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
                options:
                    - dev
                    - prod
```

New trigger:

```yaml
on:
    push:
        branches: [main]     # dev deploy path — unchanged behavior
        tags: ['v*.*.*']     # prod deploy path — replaces workflow_dispatch
```

Remove the `workflow_dispatch` environment input entirely — prod deploys should never be dispatchable against an arbitrary `main` HEAD.

### Concurrency group

Current group key reads `github.event.inputs.environment`, which won't exist on a tag push and would silently fall back to `'dev'`, incorrectly bucketing a prod deploy into the dev concurrency lane:

```yaml
concurrency:
    group: deploy-${{ github.event.inputs.environment || 'dev' }}
    cancel-in-progress: false
```

Change to key off `ref_type` instead:

```yaml
concurrency:
    group: deploy-${{ github.ref_type == 'tag' && 'prod' || 'dev' }}
    cancel-in-progress: false
```

### `build` job — tag the image with the release version

Current "Determine mutable tag" step keys off `github.event.inputs.environment`:

```yaml
- name: Determine mutable tag
  id: tag
  run: |
      if [ "${{ github.event.inputs.environment }}" = "prod" ]; then
        echo "mutable=prod" >> "$GITHUB_OUTPUT"
      else
        echo "mutable=dev" >> "$GITHUB_OUTPUT"
      fi
```

Replace with a step that keys off `ref_type` and, on a tag push, also emits the release version as an image tag:

```yaml
- name: Determine image tags
  id: tags
  run: |
      BASE="${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}"
      TAGS="$BASE:sha-${{ github.sha }}"
      if [ "${{ github.ref_type }}" = "tag" ]; then
        TAGS="$TAGS
      $BASE:${{ github.ref_name }}
      $BASE:prod"
      else
        TAGS="$TAGS
      $BASE:dev"
      fi
      {
        echo "list<<EOF"
        echo "$TAGS"
        echo "EOF"
      } >> "$GITHUB_OUTPUT"
```

And update the build-push step to use it:

```yaml
- name: Build and push
  uses: docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a # v7
  with:
      context: .
      file: ./Dockerfile
      push: true
      tags: ${{ steps.tags.outputs.list }}
      cache-from: type=gha
      cache-to: type=gha,mode=max
```

This means every prod release produces a permanently addressable image (`ghcr.io/.../fluent-ai:v26.07.3`) in addition to the mutable `:prod` tag — the versioned tag is what actually gets deployed and is what you roll back to.

### Job condition changes

`deploy-dev` — condition changes from:

```yaml
if: github.event_name == 'push' || github.event.inputs.environment == 'dev'
```

to:

```yaml
if: github.ref_type == 'branch'
```

`deploy-prod` — condition changes from:

```yaml
if: github.event.inputs.environment == 'prod'
```

to:

```yaml
if: github.ref_type == 'tag'
```

### `deploy-prod` — deploy the versioned image, not the sha

Current:

```yaml
- name: Deploy to Azure Web App
  id: deploy
  uses: azure/webapps-deploy@02a81bead70021f5284939794bcec79c271ab383 # v3
  with:
      app-name: fluent-ai-prod
      publish-profile: ${{ secrets.AZUREAPPSERVICE_PUBLISHPROFILE_PROD }}
      images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:sha-${{ github.sha }}
```

Change `images` to reference the release tag instead of the sha:

```yaml
      images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.ref_name }}
```

Functionally this points at the same commit either way, but deploying by version tag makes "what's in prod" a one-line `az webapp config container show` answer instead of a sha you have to cross-reference against git, and it's what makes rollback (§5) a simple retarget rather than a rebuild.

## 3. Optional: stamp `pyproject.toml` version from the tag

If `/health` or logs should report the running version, add to the `build` job before the Docker build step:

```yaml
- name: Install uv
  uses: astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990 # v8.3.2
  if: github.ref_type == 'tag'
  with:
      python-version: '3.14'

- name: Set version from tag
  if: github.ref_type == 'tag'
  run: uv version ${{ github.ref_name }}
```

`uv version <version>` doesn't accept a leading `v`; strip it first if needed: `uv version "${GITHUB_REF_NAME#v}"`.

## 4. Scenario walkthroughs

### Scenario A: normal release, no issues found in QA

```bash
# 1. Team merges PRs to main as usual throughout the sprint — no change to this flow.
#    Every merge auto-builds and deploys to fluent-ai-dev.

# 2. When ready to start a QA cycle, trigger the release cut:
gh workflow run cut-release.yml

# 3. Workflow computes and pushes a tag, e.g.:
#    Computed tag: v26.07.3
# This triggers post-merge-deploy.yml's prod path, which builds and pushes
# ghcr.io/eten-tech-foundation/fluent-ai:v26.07.3 and deploys it — to a QA/
# staging slot for verification if one exists (see open question in §6),
# or directly gated behind a Production environment approval (recommended).

# 4. Meanwhile, engineers keep merging PRs to main — main moves forward,
# the v26.07.3 tag does not. Nothing merged after this point is part of this release.

# 5. QA signs off. If deploy-prod is gated by a GitHub Environment protection
# rule, approve the pending deployment:
gh run list --workflow=post-merge-deploy.yml --limit 1
gh run view <run-id>   # approve the Production environment gate here
```

### Scenario B: bug found during QA, fix needed before prod

```bash
# 1. Fix is developed and merged to main as a completely normal PR.
git checkout -b fix/qa-bug-123 main
# ...make the fix...
git push -u origin fix/qa-bug-123
gh pr create --base main --title "Fix: QA bug 123"
# ...PR reviewed and merged to main via the normal pre-merge.yml gate...

# 2. Cherry-pick just that fix commit onto a short-lived branch based on the
# tag that's currently in QA (do NOT branch from main HEAD — main may have
# other unrelated work merged since the tag was cut):
git fetch --tags
git checkout -b hotfix/26.07.4 v26.07.3
git cherry-pick <fix-commit-sha>
git push -u origin hotfix/26.07.4

# 3. Cut the next release tag from this branch instead of from main:
git tag v26.07.4
git push origin v26.07.4
# This triggers the same prod-path build+deploy as Scenario A, but produces
# ghcr.io/eten-tech-foundation/fluent-ai:v26.07.4.

# 4. QA re-verifies (ideally just the delta). Once signed off, approve the
# Production environment gate the same way as step 5 in Scenario A.

# 5. Housekeeping: the fix is already on main from step 1, so no merge-back
# is needed. Delete the hotfix branch:
git push origin --delete hotfix/26.07.4
git branch -d hotfix/26.07.4
```

### Scenario C: emergency hotfix directly to prod, no pending QA cycle

```bash
# 1. Identify the tag currently running in prod:
gh release list --limit 1
# or: az webapp config container show --name fluent-ai-prod \
#       --resource-group <rg> --query "[?name=='DOCKER_CUSTOM_IMAGE_NAME'].value"

# 2. Branch from that exact tag (not main — main will have unrelated commits):
git fetch --tags
git checkout -b hotfix/26.07.5 v26.07.4
# ...make the minimal fix...
git push -u origin hotfix/26.07.5

# 3. Open a PR to main so the fix goes through the normal lint/mypy/pytest
# gate in pre-merge.yml, then merge it. main stays the source of truth for
# the fix even though the tag is cut from the hotfix branch, not main.
gh pr create --base main --title "Hotfix: <description>"

# 4. Tag directly from the hotfix branch tip (don't wait for a full release cut):
git tag v26.07.5
git push origin v26.07.5
# Builds and deploys ghcr.io/eten-tech-foundation/fluent-ai:v26.07.5 straight
# to prod via the tag-push trigger.
```

## 5. Rollback

Because every release tag maps to a permanently retained, immutable image (`ghcr.io/.../fluent-ai:v26.07.3`), rollback is retargeting the Web App at the previous image — no rebuild required:

```bash
az webapp config container set \
  --name fluent-ai-prod \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --docker-custom-image-name ghcr.io/eten-tech-foundation/fluent-ai:v26.07.3

az webapp restart --name fluent-ai-prod --resource-group "$AZURE_RESOURCE_GROUP"
```

Or re-run the workflow run associated with the previous tag to go through the full deploy path (including re-verifying `/health`):

```bash
gh run list --workflow=post-merge-deploy.yml
gh run rerun <previous-run-id>
```

**Caveat:** Alembic migrations run *before* deploy in both `deploy-dev` and `deploy-prod` (`uv run alembic upgrade head`) and are not automatically reversed by an image rollback. If the release being rolled back introduced a migration, confirm it's backward-compatible (additive) before rolling the image back, or run `alembic downgrade` manually first.

## 6. Open questions to resolve before implementing

- Does QA run against a distinct environment from `dev` (e.g. a `fluent-ai-qa` Web App), or does the release tag deploy straight into `fluent-ai-prod` behind a manual approval gate? If a dedicated QA slot is needed, add a `deploy-qa` job to `post-merge-deploy.yml` gated the same way as prod (`github.ref_type == 'tag'`) but targeting the QA app and running before `deploy-prod` (`needs: deploy-qa`).
- Should `deploy-prod` require a GitHub Environment manual-approval rule (recommended, and consistent with the existing `environment: Production` block), gating the tag-triggered run until QA explicitly signs off?
- Confirm whether `/health` should report the running version — if so, wire the `uv version` stamp from §3 through to whatever serves `/health`.
- `SERIAL` reset is implicit (derived by scanning tags) — confirm this is acceptable vs. wanting an explicit counter stored in a file.
