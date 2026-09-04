# fluent-ai: CI/CD Pipeline From Zero Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `fluent-ai` to full parity with `fluent-api`/`fluent-web`'s CI/CD pattern — PR checks, dev auto-deploy, tag-triggered releases with a commit picker, an isolated QA stage with manual approval, and prod deploy — starting from zero GitHub Actions workflows today.

**Architecture:** Containerized pipeline: build an image from the existing production `Dockerfile`, push to GHCR tagged by commit SHA, deploy to Azure Container Apps (chosen over App Service because Container Apps supports `minReplicas: 0` scale-to-zero for dev/qa, per `fluent-platform/docs/superpowers/specs/2026-08-06-cicd-pipeline-design.md`'s hosting decision — Azure stays the near-term live target, with the deploy step isolated so a later Fly.io swap is a config change, not a rebuild). Database provisioning reuses the existing `scripts/bootstrap.py` (idempotent role/schema self-provisioning) and `alembic upgrade head` pattern already used locally. Security hardening (SHA-pinned actions, CodeQL, secret scanning) is built in from day one rather than retrofitted, since there's no legacy workflow debt here.

**Tech Stack:** GitHub Actions, Docker (existing multi-stage `Dockerfile`), GHCR, `azure/login` + `az containerapp`, `uv`, `ruff`, `mypy`, `pytest`, Alembic, `actionlint`.

## Global Constraints

- CalVer tag format is exactly `vYY.MM.SERIAL`, validated against `^v[0-9]{2}\.(0[1-9]|1[0-2])\.[1-9][0-9]*$` — identical regex to `fluent-api`/`fluent-web`, do not diverge.
- `pyproject.toml`'s `version` field already reads `26.7.1` (CalVer convention already adopted per `docs/calver-versioning.md`). The release automation built here does **not** commit version bumps back to `main` — a push-back-to-main step is a non-fast-forward push whenever the commit picker selects anything other than `main`'s tip, which would break the picker. Instead the version is patched into `pyproject.toml` at **image-build time** from the tag name (Task 4), mirroring the patch-at-build convention `fluent-api` uses for `package.json`. The committed manifest version is a placeholder from this point on; `/health` reports the build-time value.
- Python version matches `requires-python = ">=3.14"` in `pyproject.toml`; use `3.14` in every workflow step that sets up Python (or route entirely through the pinned Docker image, which already uses `python:3.14-alpine3.24` pinned by digest — do not introduce a second, drifting Python version pin).
- The existing `Dockerfile` is the deploy artifact — do not create a parallel/alternate Dockerfile for CI. `EXPOSE 8200` and the existing `HEALTHCHECK` against `/health` are already correct; reuse them.
- QA must be a fully isolated instance — its own Container App, its own database (own `BOOTSTRAP_DATABASE_URL`/`MIGRATIONS_DATABASE_URL`/`DATABASE_URL`) — never sharing state with dev or prod, mirroring the isolation model already used for `fluent-api`.
- `Production-Approval` environment (or a shared cross-repo one — confirm with the team before creating; see Task 7) holds zero secrets.
- Every new workflow file must pass `actionlint` with zero errors before being committed.
- Every third-party `uses:` action reference is pinned to a full commit SHA with the version kept as a trailing comment, from the very first workflow written here — no un-pinned action ever lands in this repo's history.

---

## File Structure

- Modify: `src/app/main.py` — add `version` to the `/health` response (Task 1)
- Create: `tests/test_health.py` — test for the above (Task 1)
- Create: `.github/workflows/pre-merge.yml` — PR checks (Task 2)
- Create: `.github/dependabot.yml` update — confirm `github-actions` ecosystem present (Task 2, check existing file first)
- Create: `.github/workflows/post-merge-deploy.yml` — dev auto-deploy + QA + prod chain (Tasks 4, 7)
- Create: `.github/workflows/cut-release.yml` — tag-triggered release with commit picker (Task 5)
- Create: `scripts/cut-release.sh` — local commit picker (Task 5)
- Create: `.github/workflows/deploy-rollback.yml` — deploy-only rollback path, skips migrations (Task 8)
- Create: `docs/runbooks/deployment/prod-release-cut.md`, `prod-hotfix-during-qa.md`, `prod-emergency-hotfix.md`, `prod-rollback.md` (Task 10)
- Modify: `docs/calver-versioning.md` — replace the "Manual" fluent-ai section with the automated flow (Task 10)
- Modify: `README.md` — note `fzf` dependency (Task 5)

---

### Task 1: Expose version on `/health`

**Files:**
- Modify: `src/app/main.py`
- Create: `tests/test_health.py`

**Interfaces:**
- Consumes: `settings.app_version` (already defined in `src/app/config.py:40`, resolved via `importlib.metadata.version("fluent-ai")`, which reflects whatever version is in the installed package's `pyproject.toml` at build time).
- Produces: `/health` now returns `{"status": "healthy", "version": <str>}` — this is the field the release runbook (Task 10) and future monitoring checks read.

- [ ] **Step 1: Write the failing test**

Create `tests/test_health.py`:

```python
def test_health_returns_status_and_version(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "version" in body
    assert isinstance(body["version"], str)
    assert body["version"] != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_health.py -v`
Expected: FAIL — `assert "version" in body` fails, since today's `/health` only returns `{"status": "healthy"}`.

- [ ] **Step 3: Add version to the health endpoint**

Edit `src/app/main.py`, find:

```python
@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

Replace with:

```python
@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.app_version}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `uv run pytest tests/ -v`
Expected: all tests pass (this touches a shared endpoint — confirm nothing else asserted the old response shape).

- [ ] **Step 6: Commit**

```bash
git add src/app/main.py tests/test_health.py
git commit -m "feat(health): expose app version on /health endpoint"
```

---

### Task 2: PR checks workflow

**Files:**
- Create: `.github/workflows/pre-merge.yml`
- Modify: `.github/dependabot.yml` (check first — only edit if `github-actions` ecosystem is missing)

**Interfaces:**
- Produces: a required check named `validate` (job id) that must pass before merge — configure as a required status check in branch protection after this lands (repo Settings, not code).

- [ ] **Step 1: Resolve action SHAs before writing the file**

Per the Global Constraints, every `uses:` must be SHA-pinned from the start. Resolve each tag to its commit SHA (do this for every action referenced below):

```bash
gh api repos/actions/checkout/git/refs/tags/v7.0.0 --jq '.object.sha'
gh api repos/astral-sh/setup-uv/git/refs/tags/v7 --jq '.object.sha'
gh api repos/github/codeql-action/git/refs/tags/v4 --jq '.object.sha'
gh api repos/aquasecurity/trivy-action/git/refs/tags/v0.33.1 --jq '.object.sha'
```

If any command returns `"type":"tag"` instead of a plain SHA, resolve one level further per the method in `fluent-platform/docs/superpowers/tickets/2026-07-31-github-actions-sha-pinning.md` ("How to resolve a tag to its commit SHA"). Use the actual resolved SHAs in Step 2 below — do not reuse the illustrative SHAs from that ticket, which pin different tags.

- [ ] **Step 2: Write the workflow**

Create `.github/workflows/pre-merge.yml`:

```yaml
name: Pre-merge
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    branches: [main]

jobs:
  validate:
    runs-on: ubuntu-latest
    if: ${{ !github.event.pull_request.draft }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@<resolved-sha> # v7.0.0

      - name: Install uv
        uses: astral-sh/setup-uv@<resolved-sha> # v7
        with:
          python-version: '3.14'

      - name: Install dependencies
        run: uv sync --frozen

      - name: Lint
        run: uv run ruff check .

      - name: Format check
        run: uv run ruff format --check .

      - name: Type check
        run: uv run mypy src

      - name: Run tests with coverage gate
        run: uv run pytest tests/ -v --cov=app --cov-fail-under=$COV_BASELINE
        env:
          # Set from the measured baseline (Step 2a) — ratchet up over time, never down.
          COV_BASELINE: '<measured-baseline>'

      - name: Build image (no push — proves the Dockerfile builds clean)
        run: docker build -t fluent-ai:pr-check .

      - name: Scan image for vulnerabilities
        uses: aquasecurity/trivy-action@<resolved-sha> # v0.33.1
        with:
          image-ref: fluent-ai:pr-check
          format: table
          severity: CRITICAL,HIGH
          exit-code: '0' # non-blocking initially; flip to '1' once the finding backlog is triaged (same promotion rule as CodeQL)

  codeql:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
    steps:
      - name: Checkout repository
        uses: actions/checkout@<resolved-sha> # v7.0.0

      - name: Initialize CodeQL
        uses: github/codeql-action/init@<resolved-sha> # v4
        with:
          languages: python

      - name: Perform CodeQL Analysis
        uses: github/codeql-action/analyze@<resolved-sha> # v4
```

Note: `codeql` is a separate job from `validate` deliberately — CodeQL findings shouldn't block merge on day one (per the design spec's "non-blocking initially, promoted to blocking once the initial finding backlog is triaged"), so it's not in `validate`'s dependency chain and its own job outcome doesn't gate the PR unless branch protection is explicitly configured to require it (don't add it as a required check yet).

- [ ] **Step 2a: Measure the coverage baseline and fill in `COV_BASELINE`**

Per the design spec, the coverage threshold starts at the repo's *measured current baseline*, not an arbitrary target:

```bash
uv run pytest tests/ --cov=app --cov-report=term | tail -5
```

Round the reported total **down** to the nearest whole percent and substitute it for `<measured-baseline>` in the workflow above. Ratchet it up in future PRs as coverage improves; never lower it to make a PR pass.

- [ ] **Step 2b: Enable secret scanning and push protection**

Repo → Settings → Code security and analysis → enable **Secret scanning** and **Push protection**. Per the design spec, these apply from day one in this repo (no legacy debt). No code diff — note completion here.

- [ ] **Step 3: Run actionlint**

```bash
actionlint .github/workflows/pre-merge.yml
```

Expected: no errors. If actionlint can't resolve the action SHAs to shas (it doesn't need network access to validate syntax), this checks structural correctness, not that the SHAs are real — verify the SHAs separately by confirming the `gh api` calls in Step 1 actually returned results.

- [ ] **Step 4: Check dependabot config for github-actions ecosystem**

Run: `cat .github/dependabot.yml`

If `github-actions` is not already listed as a `package-ecosystem`, add it:

```yaml
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: daily
```

(Match the existing file's exact structure/indentation for other ecosystems already configured — don't guess at a divergent format.)

- [ ] **Step 5: Manual verification**

Open a throwaway PR against a test branch with a trivial change, confirm both `validate` and `codeql` jobs run and complete (lint/format/typecheck/test/build all pass on the existing codebase, since none of this plan's other changes have landed yet — this should be a clean pass).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/pre-merge.yml .github/dependabot.yml
git commit -m "feat(ci): add PR checks (lint, typecheck, test, build, CodeQL)"
```

---

### Task 3: Provision dev infrastructure

**Files:** none (Azure + GitHub Settings — infrastructure provisioning)

No automated test cycle — manual verification gates.

- [ ] **Step 1: Create (or confirm) an Azure Container Apps environment**

If one doesn't already exist for this project, create it (mirror whatever resource group/region the existing `fluent-api`/`fluent-web` Azure resources use, for consistency):

```bash
az containerapp env create \
  --name fluent-env \
  --resource-group <same-resource-group-as-api-and-web> \
  --location <same-region>
```

If a shared environment already exists (check with whoever manages the Azure resources before creating a duplicate), reuse it instead.

- [ ] **Step 2: Create the dev Container App**

```bash
az containerapp create \
  --name fluent-ai-dev \
  --resource-group <resource-group> \
  --environment fluent-env \
  --image mcr.microsoft.com/k8se/quickstart:latest \
  --target-port 8200 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 2
```

(The placeholder `quickstart` image is intentional — the real image gets deployed by the workflow in Task 4 on first run. `--min-replicas 0` is the scale-to-zero requirement from the design spec.)

- [ ] **Step 3: Create a service principal for GitHub Actions to deploy with, scoped to this resource group**

```bash
az ad sp create-for-rbac \
  --name "fluent-ai-gha-dev" \
  --role contributor \
  --scopes /subscriptions/<sub-id>/resourceGroups/<resource-group> \
  --sdk-auth
```

Add the full JSON output as a GitHub Actions secret named `AZURE_CREDENTIALS_DEV`.

(Consider migrating to OIDC federated credentials instead of a long-lived service-principal secret as a future hardening step — out of scope for this plan, noted for follow-up.)

- [ ] **Step 4: Provision an isolated dev database**

Create a dev-only Postgres database (or reuse whatever dev DB pattern `fluent-api` already uses, if a shared dev Postgres server exists — confirm before assuming). Add three secrets: `BOOTSTRAP_DATABASE_URL_DEV` (superuser), `MIGRATIONS_DATABASE_URL_DEV` (migrator role), `DATABASE_URL_DEV` (runtime role) — matching the three-URL bootstrap pattern `scripts/bootstrap.py` expects.

- [ ] **Step 5: Enable GHCR push permissions**

No new secret needed — `GITHUB_TOKEN` can push to GHCR when the workflow job has `permissions: packages: write`. Confirm the repo's Settings → Actions → General → Workflow permissions allows this (should be default).

- [ ] **Step 6: Create the `Development` GitHub Environment**

Repo → Settings → Environments → New environment → `Development`. No required reviewers (dev auto-deploys). Scope the dev secrets from Steps 3–4 to this environment if not already repo-level.

---

### Task 4: Dev auto-deploy workflow

**Files:**
- Create: `.github/workflows/post-merge-deploy.yml` (dev portion only — QA/prod added in Task 7)

**Interfaces:**
- Consumes: secrets from Task 3 (`AZURE_CREDENTIALS_DEV`, `BOOTSTRAP_DATABASE_URL_DEV`, `MIGRATIONS_DATABASE_URL_DEV`, `DATABASE_URL_DEV`).
- Produces: a running `fluent-ai-dev` Container App on every merge to `main`, always tracking `main`'s tip, image tagged `ghcr.io/<owner>/<repo>:<commit-sha>`.

- [ ] **Step 1: Resolve action SHAs**

```bash
gh api repos/docker/login-action/git/refs/tags/v3 --jq '.object.sha'
gh api repos/docker/build-push-action/git/refs/tags/v6 --jq '.object.sha'
gh api repos/azure/login/git/refs/tags/v2 --jq '.object.sha'
```

- [ ] **Step 2: Write the workflow (dev section)**

Create `.github/workflows/post-merge-deploy.yml`:

```yaml
name: Post-merge deploy
on:
  push:
    branches: [main]
    tags: ['v*.*.*']

jobs:
  build-push-image:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    outputs:
      image: ${{ steps.image.outputs.image }}
    steps:
      - name: Validate CalVer tag format
        if: github.ref_type == 'tag'
        run: |
          TAG="${GITHUB_REF_NAME}"
          if [[ ! "$TAG" =~ ^v[0-9]{2}\.(0[1-9]|1[0-2])\.[1-9][0-9]*$ ]]; then
            echo "::error::Tag '$TAG' does not match required CalVer format vYY.MM.SERIAL (e.g. v26.07.1)"
            exit 1
          fi
          echo "Tag '$TAG' is valid."

      - name: Checkout repository
        uses: actions/checkout@<resolved-sha> # v7.0.0

      - name: Set version in pyproject.toml
        run: |
          if [ "${GITHUB_REF_TYPE}" = "tag" ]; then
            VERSION="${GITHUB_REF_NAME#v}"
          else
            # Branch (dev) builds: keep the committed placeholder, append the short SHA
            # as a PEP-440 local version label so dev /health identifies its exact build.
            CURRENT=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
            VERSION="${CURRENT}+${GITHUB_SHA::7}"
          fi
          sed -i "s/^version = \".*\"/version = \"${VERSION}\"/" pyproject.toml
          grep "^version = \"${VERSION}\"" pyproject.toml

      - name: Log in to GHCR
        uses: docker/login-action@<resolved-sha> # v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push image
        uses: docker/build-push-action@<resolved-sha> # v6
        with:
          # `context: .` (path context) is load-bearing: it builds from the checked-out
          # workspace including the version patch above. Do not remove it — the action's
          # default Git context would silently discard the patched pyproject.toml.
          context: .
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}

      - name: Set image output
        id: image
        run: echo "image=ghcr.io/${{ github.repository }}:${{ github.sha }}" >> "$GITHUB_OUTPUT"

  migrate-dev:
    runs-on: ubuntu-latest
    needs: build-push-image
    if: github.ref_type == 'branch'
    environment: Development
    steps:
      - name: Checkout repository
        uses: actions/checkout@<resolved-sha> # v7.0.0

      - name: Install uv
        uses: astral-sh/setup-uv@<resolved-sha> # v7
        with:
          python-version: '3.14'

      - name: Install dependencies
        run: uv sync --frozen

      - name: Bootstrap schema/roles (idempotent)
        env:
          BOOTSTRAP_DATABASE_URL: ${{ secrets.BOOTSTRAP_DATABASE_URL_DEV }}
          DATABASE_URL: ${{ secrets.DATABASE_URL_DEV }}
          MIGRATIONS_DATABASE_URL: ${{ secrets.MIGRATIONS_DATABASE_URL_DEV }}
        run: uv run python scripts/bootstrap.py

      - name: Run migrations
        env:
          DATABASE_URL: ${{ secrets.MIGRATIONS_DATABASE_URL_DEV }}
        run: uv run alembic upgrade head

  deploy-dev:
    runs-on: ubuntu-latest
    needs: [build-push-image, migrate-dev]
    if: github.ref_type == 'branch'
    environment:
      name: Development
      url: https://fluent-ai-dev.<container-apps-domain>
    steps:
      - name: Azure login
        uses: azure/login@<resolved-sha> # v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS_DEV }}

      - name: Deploy image to Container App
        run: |
          az containerapp update \
            --name fluent-ai-dev \
            --resource-group <resource-group> \
            --image ${{ needs.build-push-image.outputs.image }}

      - name: Verify deployment
        run: |
          URL="https://fluent-ai-dev.<container-apps-domain>/health"
          sleep 20
          for i in $(seq 1 10); do
            response=$(curl -s -o /dev/null -w "%{http_code}" "$URL")
            if [ "$response" -ge 200 ] && [ "$response" -lt 400 ]; then
              echo "Dev deployment successful (HTTP $response)"
              exit 0
            fi
            echo "App not ready yet (HTTP $response). Retrying in 10 seconds..."
            sleep 10
          done
          echo "Dev deployment verification failed"
          exit 1
```

Replace `<resource-group>` and `<container-apps-domain>` with the actual values from Task 3's provisioning (the Container App's FQDN is printed by `az containerapp create`/`show` — capture it there rather than guessing the domain format).

Version-patching notes:
- This is where the release version enters the artifact — `cut-release.yml` (Task 5) deliberately does **not** commit a bump to `main` (see Global Constraints). `importlib.metadata.version("fluent-ai")` reads whatever was in `pyproject.toml` when the image installed the package, so patching before `docker build` is sufficient for `/health` to report correctly.
- PEP-440 normalizes `26.08.1` to `26.8.1`, so `/health` reports the tag with the month's leading zero stripped. This is expected and already documented in `docs/calver-versioning.md`'s PEP-440 note — do not "fix" it by changing the tag format.
- When a tag is cut for a commit that already had a dev build, the tag build re-pushes `ghcr.io/<repo>:<sha>` with the release version baked in (superseding the dev build's `+shortsha` variant of the same commit). Same code, same tag — only the reported version string differs.

- [ ] **Step 3: Run actionlint**

```bash
actionlint .github/workflows/post-merge-deploy.yml
```

Expected: no errors.

- [ ] **Step 4: Manual verification**

Merge to `main` (via PR through Task 2's `pre-merge.yml` checks), watch the Actions run: confirm `build-push-image` pushes to GHCR (check the repo's Packages tab), `migrate-dev` completes, `deploy-dev` updates the Container App and the smoke test against `/health` succeeds. `curl` the dev URL's `/health` manually and confirm the `version` field (Task 1) is present.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/post-merge-deploy.yml
git commit -m "feat(ci): add dev auto-deploy to Azure Container Apps"
```

---

### Task 5: `cut-release.yml` with commit picker + local script

**Files:**
- Create: `.github/workflows/cut-release.yml`
- Create: `scripts/cut-release.sh`
- Modify: `README.md`

**Interfaces:**
- Produces: `vYY.MM.SERIAL` tags, computed the same way as `fluent-api`/`fluent-web` (per-repo counter, resets monthly). The workflow is **identical** to api/web's — no manifest bump happens here. The version reaches `/health` via the image-build-time patch in Task 4's `build-push-image` job, not via a committed bump (a push-back-to-main step would be a non-fast-forward push whenever the commit picker selects an older commit, breaking the picker).

- [ ] **Step 1: Resolve action SHAs**

```bash
gh api repos/actions/checkout/git/refs/tags/v7.0.0 --jq '.object.sha'
gh api repos/softprops/action-gh-release/git/refs/tags/v2 --jq '.object.sha'
```

- [ ] **Step 2: Write `cut-release.yml`**

```yaml
name: Cut release
on:
  workflow_dispatch:
    inputs:
      commit:
        description: 'Commit SHA on main to release (leave blank for latest main)'
        required: false
        type: string

concurrency: release

jobs:
  tag:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@<resolved-sha> # v7.0.0
        with:
          ref: ${{ inputs.commit || 'main' }}
          fetch-depth: 0
          token: ${{ secrets.BOT_TOKEN }}
          persist-credentials: true

      - name: Validate chosen commit is on main
        if: inputs.commit != ''
        env:
          COMMIT: ${{ inputs.commit }}
        run: |
          git fetch origin main --quiet
          if ! git merge-base --is-ancestor "$COMMIT" origin/main; then
            echo "::error::Commit $COMMIT is not reachable from main. Choose a commit already merged to main."
            exit 1
          fi
          echo "Commit $COMMIT confirmed on main."

      - name: Compute CalVer tag
        id: version
        run: |
          YEAR_MONTH=$(date +'%y.%m')
          SERIAL=$(git tag -l "v${YEAR_MONTH}.[0-9]*" | sed -E "s/^v${YEAR_MONTH}\.//" | sort -n | tail -1)
          SERIAL=${SERIAL:-0}
          NEXT=$((SERIAL + 1))
          TAG="v${YEAR_MONTH}.${NEXT}"
          echo "tag=$TAG" >> "$GITHUB_OUTPUT"
          echo "Computed tag: $TAG"

      - name: Validate CalVer tag format
        env:
          TAG: ${{ steps.version.outputs.tag }}
        run: |
          if [[ ! "$TAG" =~ ^v[0-9]{2}\.(0[1-9]|1[0-2])\.[1-9][0-9]*$ ]]; then
            echo "::error::Tag '$TAG' does not match required CalVer format vYY.MM.SERIAL (e.g. v26.07.1)"
            exit 1
          fi
          echo "Tag '$TAG' is valid."

      - name: Tag and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git tag ${{ steps.version.outputs.tag }}
          git push origin ${{ steps.version.outputs.tag }}

      - name: Create GitHub release
        uses: softprops/action-gh-release@<resolved-sha> # v2
        with:
          tag_name: ${{ steps.version.outputs.tag }}
          generate_release_notes: true
```

This file is deliberately **byte-for-byte identical** to `fluent-api`/`fluent-web`'s `cut-release.yml`. An earlier draft of this plan bumped and committed `pyproject.toml` here and pushed it back to `main` — that approach is incompatible with the commit picker (checking out an older `inputs.commit`, committing on top, and pushing `HEAD:main` is a non-fast-forward push that gets rejected, and races with any concurrent merge). The version instead reaches `/health` via the image-build-time patch from the tag name in Task 4's `build-push-image` job, matching `fluent-api`'s patch-at-build convention with `jq`/`package.json`. Update `docs/calver-versioning.md`'s manual-bump instructions accordingly in Task 10.

- [ ] **Step 3: Run actionlint**

```bash
actionlint .github/workflows/cut-release.yml
```

Expected: no errors.

- [ ] **Step 4: Write the local picker script**

Create `scripts/cut-release.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

git fetch origin main --quiet
COMMIT=$(git log --oneline -30 origin/main | fzf --prompt="Pick a commit to release: " | cut -d' ' -f1)
[ -n "$COMMIT" ] || { echo "No commit selected"; exit 1; }
echo "Cutting release from commit: $COMMIT"
gh workflow run cut-release.yml -f commit="$COMMIT"
```

```bash
chmod +x scripts/cut-release.sh
shellcheck scripts/cut-release.sh
```

Expected: no shellcheck warnings.

- [ ] **Step 5: Document the `fzf` dependency**

Add to `README.md`'s prerequisites section:

```markdown
- [`fzf`](https://github.com/junegunn/fzf#installation) — required for `scripts/cut-release.sh` (interactive commit picker for cutting releases)
```

- [ ] **Step 6: Manual verification**

Confirm the `BOT_TOKEN` secret already exists in this repo (it's referenced but not yet used here) — if it doesn't, this step blocks on creating it the same way `fluent-api`/`fluent-web` did (check with whoever set those up; likely a machine-user PAT or GitHub App). Run "Cut release" with a blank `commit`, confirm the tag and GitHub Release are created. Then run it with `commit` set to an older SHA on `main` — confirm the tag points at that commit — and with an off-`main` SHA — confirm the ancestry check fails and no tag is created. Delete throwaway tags afterward so they don't collide with the next real release's serial computation.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/cut-release.yml scripts/cut-release.sh README.md
git commit -m "feat(release): add cut-release.yml with commit picker"
```

---

### Task 6: Provision QA infrastructure

**Files:** none (Azure + GitHub Settings)

Mirrors Task 3, QA-scoped. No automated test cycle.

- [ ] **Step 1: Create the QA Container App**

```bash
az containerapp create \
  --name fluent-ai-qa \
  --resource-group <resource-group> \
  --environment fluent-env \
  --image mcr.microsoft.com/k8se/quickstart:latest \
  --target-port 8200 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 2
```

- [ ] **Step 2: Create a QA-scoped service principal**

```bash
az ad sp create-for-rbac \
  --name "fluent-ai-gha-qa" \
  --role contributor \
  --scopes /subscriptions/<sub-id>/resourceGroups/<resource-group> \
  --sdk-auth
```

Add as secret `AZURE_CREDENTIALS_QA`.

- [ ] **Step 3: Provision an isolated QA database**

Fully separate from dev and prod. Add `BOOTSTRAP_DATABASE_URL_QA`, `MIGRATIONS_DATABASE_URL_QA`, `DATABASE_URL_QA`.

- [ ] **Step 4: Create the `QA` GitHub Environment**

Repo → Settings → Environments → New environment → `QA`. No required reviewers.

---

### Task 7: QA deploy stage + prod approval gate

**Files:**
- Modify: `.github/workflows/post-merge-deploy.yml` (add QA and prod jobs)

**Interfaces:**
- Consumes: `build-push-image` job's `image` output (Task 4), Task 6's QA secrets.
- Produces: `deploy-qa` (mirrors `deploy-dev`'s shape against `fluent-ai-qa`), `approve-prod` gate, `migrate-prod`/`deploy-prod` gated on approval.

- [ ] **Step 1: Baseline actionlint check**

```bash
actionlint .github/workflows/post-merge-deploy.yml
```

- [ ] **Step 2: Create the `Production-Approval` environment (or confirm a shared one)**

Check whether `fluent-api`/`fluent-web` already have a `Production-Approval` environment (per their equivalent plans) that this repo should also target with the same reviewer list, or whether each repo should have its own. Decide with the team before creating — this is an open question flagged in the design spec. If per-repo: Repo → Settings → Environments → New environment → `Production-Approval`, add required reviewers, **no secrets**.

- [ ] **Step 3: Add `migrate-qa`, `deploy-qa`, `approve-prod`, `migrate-prod`, `deploy-prod` jobs**

Append to `.github/workflows/post-merge-deploy.yml` (resolve `azure/login`'s SHA the same way as Task 4 if not already resolved):

```yaml
  migrate-qa:
    runs-on: ubuntu-latest
    needs: build-push-image
    if: github.ref_type == 'tag'
    environment: QA
    steps:
      - name: Checkout repository
        uses: actions/checkout@<resolved-sha> # v7.0.0

      - name: Install uv
        uses: astral-sh/setup-uv@<resolved-sha> # v7
        with:
          python-version: '3.14'

      - name: Install dependencies
        run: uv sync --frozen

      - name: Bootstrap schema/roles (idempotent)
        env:
          BOOTSTRAP_DATABASE_URL: ${{ secrets.BOOTSTRAP_DATABASE_URL_QA }}
          DATABASE_URL: ${{ secrets.DATABASE_URL_QA }}
          MIGRATIONS_DATABASE_URL: ${{ secrets.MIGRATIONS_DATABASE_URL_QA }}
        run: uv run python scripts/bootstrap.py

      - name: Run migrations
        env:
          DATABASE_URL: ${{ secrets.MIGRATIONS_DATABASE_URL_QA }}
        run: uv run alembic upgrade head

  deploy-qa:
    runs-on: ubuntu-latest
    needs: [build-push-image, migrate-qa]
    if: github.ref_type == 'tag'
    environment:
      name: QA
      url: https://fluent-ai-qa.<container-apps-domain>
    steps:
      - name: Azure login
        uses: azure/login@<resolved-sha> # v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS_QA }}

      - name: Deploy image to Container App
        run: |
          az containerapp update \
            --name fluent-ai-qa \
            --resource-group <resource-group> \
            --image ${{ needs.build-push-image.outputs.image }}

      - name: Verify deployment
        run: |
          URL="https://fluent-ai-qa.<container-apps-domain>/health"
          sleep 20
          for i in $(seq 1 10); do
            response=$(curl -s -o /dev/null -w "%{http_code}" "$URL")
            if [ "$response" -ge 200 ] && [ "$response" -lt 400 ]; then
              echo "QA deployment successful (HTTP $response)"
              exit 0
            fi
            echo "App not ready yet (HTTP $response). Retrying in 10 seconds..."
            sleep 10
          done
          echo "QA deployment verification failed"
          exit 1

      - name: Post deployment marker
        env:
          WEBHOOK: ${{ secrets.DEPLOY_MARKER_WEBHOOK_URL }}
        run: |
          if [ -z "$WEBHOOK" ]; then echo "No DEPLOY_MARKER_WEBHOOK_URL configured; skipping marker"; exit 0; fi
          curl -fsS -X POST -H 'Content-Type: application/json' \
            -d "{\"service\":\"fluent-ai\",\"environment\":\"qa\",\"tag\":\"${GITHUB_REF_NAME}\",\"sha\":\"${GITHUB_SHA}\"}" \
            "$WEBHOOK"

  approve-prod:
    runs-on: ubuntu-latest
    needs: deploy-qa
    if: github.ref_type == 'tag'
    environment:
      name: Production-Approval
    steps:
      - run: echo "QA sign-off received — proceeding to production deploy."

  migrate-prod:
    runs-on: ubuntu-latest
    needs: [build-push-image, approve-prod]
    if: github.ref_type == 'tag'
    environment: Production
    steps:
      - name: Checkout repository
        uses: actions/checkout@<resolved-sha> # v7.0.0

      - name: Install uv
        uses: astral-sh/setup-uv@<resolved-sha> # v7
        with:
          python-version: '3.14'

      - name: Install dependencies
        run: uv sync --frozen

      - name: Bootstrap schema/roles (idempotent)
        env:
          BOOTSTRAP_DATABASE_URL: ${{ secrets.BOOTSTRAP_DATABASE_URL_PROD }}
          DATABASE_URL: ${{ secrets.DATABASE_URL_PROD }}
          MIGRATIONS_DATABASE_URL: ${{ secrets.MIGRATIONS_DATABASE_URL_PROD }}
        run: uv run python scripts/bootstrap.py

      - name: Run migrations
        env:
          DATABASE_URL: ${{ secrets.MIGRATIONS_DATABASE_URL_PROD }}
        run: uv run alembic upgrade head

  deploy-prod:
    runs-on: ubuntu-latest
    needs: [build-push-image, migrate-prod]
    if: github.ref_type == 'tag'
    environment:
      name: Production
      url: https://fluent-ai-prod.<container-apps-domain>
    steps:
      - name: Azure login
        uses: azure/login@<resolved-sha> # v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS_PROD }}

      - name: Deploy image to Container App
        run: |
          az containerapp update \
            --name fluent-ai-prod \
            --resource-group <resource-group> \
            --image ${{ needs.build-push-image.outputs.image }}

      - name: Verify deployment
        run: |
          URL="https://fluent-ai-prod.<container-apps-domain>/health"
          sleep 30
          for i in $(seq 1 12); do
            response=$(curl -s -o /dev/null -w "%{http_code}" "$URL")
            if [ "$response" -ge 200 ] && [ "$response" -lt 400 ]; then
              echo "Production deployment successful (HTTP $response)"
              exit 0
            fi
            echo "App not ready yet (HTTP $response). Retrying in 15 seconds..."
            sleep 15
          done
          echo "Production deployment verification failed"
          exit 1

      - name: Post deployment marker
        env:
          WEBHOOK: ${{ secrets.DEPLOY_MARKER_WEBHOOK_URL }}
        run: |
          if [ -z "$WEBHOOK" ]; then echo "No DEPLOY_MARKER_WEBHOOK_URL configured; skipping marker"; exit 0; fi
          curl -fsS -X POST -H 'Content-Type: application/json' \
            -d "{\"service\":\"fluent-ai\",\"environment\":\"production\",\"tag\":\"${GITHUB_REF_NAME}\",\"sha\":\"${GITHUB_SHA}\"}" \
            "$WEBHOOK"
```

Deployment markers implement the design spec's "Observability on deploy" requirement (every successful `deploy-qa`/`deploy-prod` posts a one-line greppable marker). `DEPLOY_MARKER_WEBHOOK_URL` is a repo-level secret pointing at wherever the org's monitoring lives (a Slack incoming webhook is the minimum viable version). The step degrades to a logged skip when the secret isn't configured yet, so the pipeline doesn't block on the monitoring decision.

This requires provisioning a prod Container App, prod service principal (`AZURE_CREDENTIALS_PROD`), and prod database secrets the same way Tasks 3/6 did for dev/QA — add that provisioning as part of this step if not already done (list it explicitly, don't skip silently):

- [ ] **Step 3a: Provision prod Container App + service principal + database, mirroring Task 6's pattern exactly, scoped to `-prod` instead of `-qa`.**

- [ ] **Step 4: Run actionlint**

```bash
actionlint .github/workflows/post-merge-deploy.yml
```

Expected: no errors.

- [ ] **Step 5: Manual dry-run verification**

Cut a release (Task 5) against a test-safe commit. Watch: `migrate-qa`/`deploy-qa` succeed automatically, `approve-prod` shows "Waiting" in the Actions UI, approve it, confirm `migrate-prod`/`deploy-prod` then run and the prod `/health` reflects the new version.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/post-merge-deploy.yml
git commit -m "feat(release): add QA and production deploy stages with approval gate"
```

---

### Task 8: Deploy-only rollback path

**Files:**
- Create: `.github/workflows/deploy-rollback.yml`

**Interfaces:**
- Consumes: an existing `vYY.MM.SERIAL` tag (`inputs.tag`) and the GHCR image already pushed for that tag's commit by Task 4's `build-push-image` (`ghcr.io/<owner>/fluent-ai:<sha>`). No rebuild, no migrations — the entire point.
- Produces: the prod Container App running the prior tag's image. Mirrors `fluent-api`/`fluent-web`'s `deploy-rollback.yml` so rollback never requires an engineer's personal Azure credentials and a hand-typed `az` command.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/deploy-rollback.yml`:

```yaml
name: Deploy rollback (no migration)
on:
  workflow_dispatch:
    inputs:
      tag:
        description: 'Existing vYY.MM.SERIAL tag to redeploy to production, without running migrations'
        required: true
        type: string

jobs:
  deploy-prod:
    runs-on: ubuntu-latest
    environment:
      name: Production
      url: https://fluent-ai-prod.<container-apps-domain>
    steps:
      - name: Validate tag format
        env:
          TAG: ${{ inputs.tag }}
        run: |
          if [[ ! "$TAG" =~ ^v[0-9]{2}\.(0[1-9]|1[0-2])\.[1-9][0-9]*$ ]]; then
            echo "::error::Tag '$TAG' does not match required CalVer format vYY.MM.SERIAL (e.g. v26.07.1)"
            exit 1
          fi
          echo "Tag '$TAG' is valid."

      - name: Checkout repository (full history, for tag resolution)
        uses: actions/checkout@<resolved-sha> # v7.0.0
        with:
          fetch-depth: 0

      - name: Resolve tag to image reference
        id: image
        env:
          TAG: ${{ inputs.tag }}
        run: |
          SHA=$(git rev-list -n 1 "$TAG") || { echo "::error::Tag $TAG not found"; exit 1; }
          echo "image=ghcr.io/${GITHUB_REPOSITORY}:${SHA}" >> "$GITHUB_OUTPUT"
          echo "Rolling back to $TAG ($SHA)"

      - name: Azure login
        uses: azure/login@<resolved-sha> # v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS_PROD }}

      - name: Deploy image to Container App
        run: |
          az containerapp update \
            --name fluent-ai-prod \
            --resource-group <resource-group> \
            --image ${{ steps.image.outputs.image }}

      - name: Verify deployment
        run: |
          URL="https://fluent-ai-prod.<container-apps-domain>/health"
          sleep 30
          for i in $(seq 1 12); do
            response=$(curl -s -o /dev/null -w "%{http_code}" "$URL")
            if [ "$response" -ge 200 ] && [ "$response" -lt 400 ]; then
              echo "Rollback deployment successful (HTTP $response)"
              exit 0
            fi
            echo "App not ready yet (HTTP $response). Retrying in 15 seconds..."
            sleep 15
          done
          echo "Rollback deployment verification failed"
          exit 1

      - name: Post deployment marker
        env:
          WEBHOOK: ${{ secrets.DEPLOY_MARKER_WEBHOOK_URL }}
          TAG: ${{ inputs.tag }}
        run: |
          if [ -z "$WEBHOOK" ]; then echo "No DEPLOY_MARKER_WEBHOOK_URL configured; skipping marker"; exit 0; fi
          curl -fsS -X POST -H 'Content-Type: application/json' \
            -d "{\"service\":\"fluent-ai\",\"environment\":\"production\",\"tag\":\"${TAG}\",\"event\":\"rollback\"}" \
            "$WEBHOOK"
```

Note: this workflow deliberately has **no migration job** — that's the entire point. Per the decided policy in `fluent-platform/docs/superpowers/specs/2026-08-06-cicd-pipeline-design.md`, it does **not** go through `Production-Approval` (the rollback is itself the emergency response) but runs under the `Production` environment, inheriting whatever protection rules that environment carries. Same policy as `fluent-api`/`fluent-web`'s rollback workflows.

- [ ] **Step 2: Run actionlint**

```bash
actionlint .github/workflows/deploy-rollback.yml
```

Expected: no errors.

- [ ] **Step 3: Manual verification**

Do not test against real prod first. Temporarily point a copy of the workflow at `fluent-ai-dev`/`AZURE_CREDENTIALS_DEV`, run it against an existing tag, confirm it deploys the prior image with no migration step anywhere in the run, then revert the temporary change. Alternatively, in a safe prod window, run it against the tag currently live in prod (a user-invisible no-op) to prove the mechanism.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy-rollback.yml
git commit -m "feat(release): add deploy-only rollback workflow that skips migrations"
```

---

### Task 9: Tag governance rulesets

**Files:** none (GitHub repo Settings)

Identical to the `fluent-api` plan's Task 6 — apply the same two-ruleset pattern here.

- [ ] **Step 1: Confirm the bot identity** used by `secrets.BOT_TOKEN` (Task 5).
- [ ] **Step 2: Create Ruleset A** ("Restrict release tag creation") on pattern `v*.*.*`, "Restrict creations" only, bypass = bot identity **plus the Repository admin role** — admins need it to hand-push hotfix tags per the runbooks in Task 10; without it those runbooks are blocked exactly during an incident.
- [ ] **Step 3: Create Ruleset B** ("Protect release tag immutability") on pattern `v*.*.*`, "Restrict deletions" + "Block force pushes", bypass empty/admins-only.
- [ ] **Step 4: Verify** by attempting a hand-created/deleted/force-pushed tag as a non-bypassed account and confirming rejection, then confirming an admin **can** create (but not delete/move) a `v*.*.*` tag.

---

### Task 10: Runbooks and docs update

**Files:**
- Create: `docs/runbooks/deployment/prod-release-cut.md`
- Create: `docs/runbooks/deployment/prod-hotfix-during-qa.md`
- Create: `docs/runbooks/deployment/prod-emergency-hotfix.md`
- Create: `docs/runbooks/deployment/prod-rollback.md`
- Modify: `docs/calver-versioning.md`

- [ ] **Step 1: Create `docs/runbooks/deployment/prod-release-cut.md`**

```markdown
# Runbook: Cut a production release

1. Ensure `main` is in the state you want to release (or know the exact commit SHA, if not HEAD).
2. Run `./scripts/cut-release.sh` locally, or trigger "Cut release" manually from the Actions tab, filling in `commit` if not releasing HEAD.
3. Confirm the tag and GitHub Release were created. (No version-bump commit lands on `main` — the version is patched into the image at build time from the tag.)
4. Watch `migrate-qa` → `deploy-qa` complete automatically.
5. Verify QA manually (`curl https://fluent-ai-qa.../health`).
6. Approve the `Production-Approval` gate.
7. Confirm `migrate-prod` and `deploy-prod` complete.
8. Confirm prod `/health` reflects the new version.
```

- [ ] **Step 2: Create `docs/runbooks/deployment/prod-hotfix-during-qa.md`**

```markdown
# Runbook: Hotfix a bug found during QA sign-off

> **Prerequisite:** hand-pushing a `v*.*.*` tag requires the Repository admin role —
> tag creation is restricted by ruleset (bot + admins only). If you aren't an admin,
> get one on the call now.

1. Fix lands on `main` via a normal PR.
2. Cherry-pick onto a short-lived branch cut from the tag currently in QA:

   ```bash
   git fetch --tags
   git checkout -b hotfix/26.07.4 v26.07.3
   git cherry-pick <fix-commit-sha>
   git push -u origin hotfix/26.07.4
   ```

3. `cut-release.yml` only runs against `main`. Tag the hotfix branch tip manually, following the `vYY.MM.N` contract (next serial for the current month). No `pyproject.toml` bump is needed — the build patches the version from the tag:

   ```bash
   git tag v26.07.4
   git push origin v26.07.4
   ```

4. This triggers the same QA → approval → prod chain as a normal release.
```

- [ ] **Step 3: Create `docs/runbooks/deployment/prod-emergency-hotfix.md`**

```markdown
# Runbook: Emergency hotfix (prod broken, no pending QA cycle)

> **Prerequisite:** hand-pushing a `v*.*.*` tag requires the Repository admin role —
> tag creation is restricted by ruleset (bot + admins only).

1. Identify the tag currently live in prod (`curl https://fluent-ai-prod.../health`).
2. Branch from that tag, not `main`:

   ```bash
   git fetch --tags
   git checkout -b hotfix/<next-tag> v<current-prod-tag>
   ```

3. Fix the issue on this branch, then tag and push the branch tip (no `pyproject.toml` bump — the build patches the version from the tag):

   ```bash
   git tag v<next-tag>
   git push origin hotfix/<next-tag> v<next-tag>
   ```

4. Open a PR to `main` afterward for the historical record.
5. This still goes through QA → `Production-Approval` → prod. If the emergency genuinely can't wait for a QA cycle, that's a call for whoever holds `Production-Approval` reviewer access to make explicitly.
```

- [ ] **Step 4: Create `docs/runbooks/deployment/prod-rollback.md`**

```markdown
# Runbook: Roll back a production release

**Do not** attempt to re-run `Post-merge deploy` against a prior tag — even where possible, it would re-run migrations, which is not what a rollback wants and can be actively harmful if the release being rolled back included a schema migration.

1. Identify the prior tag to roll back to (`git tag -l 'v*' --sort=-creatordate | head -5`).
2. Before proceeding: confirm the prior release's code is compatible with the **current** database schema — do not assume. If the release being rolled back applied a migration, rolling back the app code without handling the schema can break the app.
3. Trigger the "Deploy rollback (no migration)" workflow from the Actions tab, with `tag` set to the prior tag. It resolves the tag to its already-built GHCR image and redeploys it — no rebuild, no migrations.
4. Confirm the workflow's verify step passes and `/health` reflects the rolled-back version.
5. This does **not** go through `Production-Approval` — a rollback is itself the emergency response (decided policy, per the design spec; same as fluent-api/fluent-web).
```

- [ ] **Step 5: Update `docs/calver-versioning.md`**

Replace the existing `### fluent-ai (Manual)` section and its "How to release a new version" subsection with:

```markdown
### `fluent-api`, `fluent-web`, and `fluent-ai` (Automated)

All three repositories now follow the same tag-based release flow.

**Flow:**
1. Go to GitHub Actions and manually trigger the **Cut release** workflow on `main` (or run `./scripts/cut-release.sh` for an interactive commit picker).
2. The workflow computes the next `vYY.MM.SERIAL` tag, tags the chosen commit, and pushes.
3. Pushing the tag triggers **Post-merge deploy**: build → QA deploy → manual `Production-Approval` sign-off → prod deploy. No new tag is cut for the prod step.
4. `fluent-ai` patches `pyproject.toml`'s `version` field at **image-build time** from the tag name (its version is read from installed package metadata at runtime via `importlib.metadata`) — the committed manifest version is a placeholder and is never bumped by the release flow, mirroring how `fluent-api` patches `package.json` at deploy time.

See `docs/runbooks/deployment/` for hotfix, emergency, and rollback procedures.
```

Keep the "Note for Python: Python's PEP-440 versioning..." caveat — it still applies: the build-time patch writes the tag's version into `pyproject.toml`, and PEP-440 normalization strips the month's leading zero, so `/health` reports `26.8.1` for tag `v26.08.1`. That mapping is expected, not a bug.

- [ ] **Step 6: Commit**

```bash
git add docs/runbooks docs/calver-versioning.md
git commit -m "docs(release): add deployment runbooks and update to automated flow"
```

---

## Self-Review Notes

- **Spec coverage:** PR checks + coverage gate + Trivy + secret scanning ✓ (Task 2), dev auto-deploy ✓ (Tasks 3–4), commit picker ✓ (Task 5), QA isolation + approval gate + deployment markers ✓ (Tasks 6–7), deploy-only rollback workflow ✓ (Task 8), version visibility ✓ (Task 1), SHA-pinning/CodeQL from day one ✓ (Tasks 2, 4, 5, 7, 8 all SHA-pin from the start), tag governance ✓ (Task 9), runbooks ✓ (Task 10). Deployment markers use a `DEPLOY_MARKER_WEBHOOK_URL` secret that degrades to a logged skip until the org's monitoring destination is decided.
- **Versioning correctness:** `cut-release.yml` is identical to api/web's — no commit-back-to-main (which would be a non-fast-forward push whenever the commit picker selects an older commit). The version reaches `/health` via the build-time `pyproject.toml` patch in `build-push-image` (Task 4), with the PEP-440 leading-zero normalization caveat documented there.
- **Placeholder scan:** no TBDs. `<resolved-sha>`, `<resource-group>`, `<container-apps-domain>`, `<sub-id>`, `<measured-baseline>` are explicitly marked as values to fill from real Azure/`gh api`/coverage output at implementation time, not vague placeholders — each has an explicit preceding step showing how to obtain the real value.
- **Type/name consistency:** secret names (`AZURE_CREDENTIALS_DEV/QA/PROD`, `BOOTSTRAP_DATABASE_URL_*`, `MIGRATIONS_DATABASE_URL_*`, `DATABASE_URL_*`, `DEPLOY_MARKER_WEBHOOK_URL`) and Container App names (`fluent-ai-dev/qa/prod`) are used consistently across Tasks 3, 4, 6, 7, 8, and the runbooks in Task 10.
- **Runbook/ruleset coherence:** hotfix runbooks require hand-pushed tags; Ruleset A's bypass therefore includes the Repository admin role (Task 9), and each hotfix runbook states that prerequisite up front.
