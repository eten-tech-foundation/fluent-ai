# Production Rollback

Rolling back is a normal promotion of an older commit. Nothing special is
required, because production deploys an immutable image identified by SHA and
every previously released commit still has one.

## 1. Find the commit to go back to

The commit currently live:

```bash
curl -s https://fluent-ai-prod.azurewebsites.net/health | jq -r .commit
```

The commit you want instead — usually the previous release, which you can read
off the earlier **Promote to Production** run in the Actions history, or from
`main`:

```bash
git log --oneline origin/main
```

## 2. Check whether it needs a QA pass

Every commit promoted through the happy path already has a `qa-<commit>` tag,
so **Promote to Production** will accept it straight away.

If it does not (an old commit that predates the QA gate), run **Deploy to QA**
for it first. That is usually worth doing anyway: rolling back re-runs that
build against *today's* database, which has migrations the old build has not
seen.

## 3. Promote it

**Actions → Promote to Production → Run workflow**, entering the SHA. Approve
the `production` deployment. Verify with `/health` as in
[the release runbook](prod-release.md).

> [!CAUTION]
> **Rolling back code does not roll back the database.** `alembic upgrade head`
> is run at every deploy and is never automatically reversed, so the old build
> starts against a schema newer than the one it was written for. That is fine
> for additive migrations and is not fine for a migration that dropped or
> renamed something. If the release you are backing out included a destructive
> migration, roll the schema back deliberately — `alembic downgrade <rev>`
> against `MIGRATIONS_DATABASE_URL` — before promoting the older commit, and
> take a backup first.

> [!TIP]
> Rolling *forward* with a fix is usually safer than rolling back, for exactly
> the reason above. Prefer it when the fix is small and the fault is not
> actively causing damage.
