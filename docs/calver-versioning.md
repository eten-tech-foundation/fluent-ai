# Fluent Calendar Versioning (CalVer)

Across the Fluent repositories, we use Calendar Versioning (CalVer) for release versioning.

## Scheme

We use the strict format:

```text
YY.MM.SERIAL
```

- `YY` — two-digit year (e.g. `26` for 2026)
- `MM` — two-digit month (e.g. `07` or `11`). We enforce leading zeros for consistency.
- `SERIAL` — an auto-incrementing integer for each release within the month (e.g. `1`, `2`, `3`). It resets to `1` on the first release of a new month.

**Examples:**
- `26.07.1` (First release in July 2026)
- `26.07.2` (Second release in July 2026)
- `26.11.1` (First release in November 2026)

## Repositories

### `fluent-api` and `fluent-web` (Automated)

In these repositories, production deployments are strictly **Tag-Based**.

**Flow:**
1. You go to GitHub Actions and manually trigger the **Cut release** workflow on the `main` branch.
2. The workflow automatically calculates the next `vYY.MM.SERIAL` tag (with leading zeros), tags the commit, and pushes the tag to GitHub.
3. Pushing the `v*.*.*` tag automatically triggers the **Post-merge Deploy** workflow.
4. The deployment runner checks out the exact tag. 
5. To inject the version into the build without crashing Strict SemVer parsers (like `npm`), the CI pipeline dynamically parses the configuration using tools like `jq` or env vars (`VITE_APP_VERSION`), completely bypassing `npm version`.
6. The app is built and securely deployed to Azure. (`fluent-web` enforces `--frozen-lockfile` for reproducible rollbacks.)

### `fluent-ai` (Automated, but **SHA-based**)

`fluent-ai` has deployment automation — see [`docs/runbooks/deployment/`](runbooks/deployment/) — but it does **not** deploy by tag. It ships a container image, and every commit on `main` is built once as `sha-<commit>`; QA and production promote that image by commit SHA. `/health` reports the commit that is live.

CalVer in `fluent-ai` is therefore a **human-facing version string only**. It marks a release for changelogs and support conversations; it does not select what deploys, and pushing a tag deploys nothing.

> [!NOTE]
> This is a real divergence from `fluent-api` and `fluent-web`, where the tag *is* the deployment unit. A release cut across all three repos has no single identifier today. Whether `fluent-ai` should grow a `Cut release` workflow and promote by tag is an open question, deliberately left out of the workflow it would change.

**Note for Python:** Python's PEP-440 versioning standard automatically strips leading zeros. While the global spec is `26.07.1`, Python will natively format it as `26.7.1` in `pyproject.toml`. This is expected behavior.

### How to release a new version in `fluent-ai`

1. Update `version` in `pyproject.toml` to the next CalVer string (e.g., `26.7.1`).
2. Commit with `chore(release): vYY.MM.SERIAL`.
3. Tag the commit (e.g. `vYY.MM.SERIAL`) and push.
4. Deploy it by SHA, following [the release runbook](runbooks/deployment/prod-release.md). The tag push does not deploy anything on its own.

## Visibility

- **fluent-api**: The version is exposed via the `/health` endpoint.
- **fluent-web**: The version is visible in the UI diagnostic footer.
- **fluent-ai**: The `/health` endpoint reports `version`, `environment` and the deployed `commit`. The commit is the authoritative answer to "what is running here".
