# Production Release (Happy Path)

Releasing is two manual workflow runs with your testing in between: deploy a
commit to QA, test it, then promote that same commit to production.

## 1. Pick the commit

Any commit on `main` that has finished building. The head of `main` is the
usual choice — leave the SHA blank to get it.

```bash
git fetch origin
git rev-parse origin/main
```

## 2. Deploy it to QA

**Actions → Deploy to QA → Run workflow.** Paste the full 40-character SHA, or
leave it blank for the head of `main`.

The run resolves the SHA, confirms it is reachable from `main`, confirms its
image exists in GHCR, migrates the QA database, deploys, and waits for
`/health` on `fluent-ai-qa` to report that commit. It finishes by tagging the
image `qa-<commit>` — that tag is what production will check for.

## 3. Test QA

```bash
curl -s https://fluent-ai-qa.azurewebsites.net/health | jq
```

Confirm `commit` is the SHA you deployed and `environment` is `production`.

> [!NOTE]
> QA runs with `ENVIRONMENT=production` on purpose, so it exercises the same
> logging, error handling and startup checks production will. One consequence:
> the dev admin API key is **not** seeded in QA (`src/app/db/seeds/api_keys.py`
> gates that on `is_production`). `ADMIN_API_KEY_HASH` is only the SHA-256 the
> app checks presented keys against — it cannot issue one, and sending the hash
> itself will not authenticate. Use the plaintext key whose hash it is, from
> the secrets manager, and provision one per
> [the API key runbook](../../guides/api-key-runbook.md) if QA has none.

## 4. Promote to production

**Actions → Promote to Production → Run workflow.** Enter the same SHA. Leave
`skip_qa_check` unticked.

The run refuses the SHA if it has no `qa-<commit>` tag, then pauses for the
`production` environment's required reviewers. Approve it: **Review
deployments → production → Approve and deploy**.

Migrations run first. If they fail, the job stops there and the new image is
never deployed.

## 5. Verify production

```bash
curl -s https://fluent-ai-prod.azurewebsites.net/health | jq
```

`commit` must be the SHA you promoted.

> [!IMPORTANT]
> If nobody approves, production is simply never deployed — QA keeps running
> the build and nothing is lost. GitHub expires a pending approval after 30
> days; re-run **Promote to Production** for the same SHA to ship it after that.

> [!WARNING]
> Merging to `main` deploys **dev only**. Pushing a git tag deploys nothing.
> Only **Deploy to QA** and **Promote to Production** reach those environments.
