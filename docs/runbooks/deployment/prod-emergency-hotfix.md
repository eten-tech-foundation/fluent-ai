# Production Emergency Hotfix

Production is broken and the fix cannot wait for a normal release.

The fix still goes through `main`. There is no branch-to-production path: images
are built only for commits on `main`, and **Deploy to QA** refuses a commit that
is not reachable from `main`. This is deliberate — the least-tested code should
not get the shortest path.

## 1. Land the fix on `main`

Open a PR as normal and merge it. Keep it as small as it can be.

**Build, Migrate & Deploy (Dev)** then builds the merge commit and deploys it to
dev. Wait for that run to finish — production cannot ship a commit whose image
does not exist yet.

```bash
git fetch origin
git rev-parse origin/main
```

## 2. Deploy it to QA, even now

**Actions → Deploy to QA → Run workflow**, blank for the head of `main`.

It is one workflow run, and it is what makes step 3 a normal promotion rather
than a bypass. Check `/health` on `fluent-ai-qa` reports the commit, and
exercise the broken path.

## 3. Promote it

**Actions → Promote to Production → Run workflow**, entering the SHA. Approve
the `production` deployment, then verify:

```bash
curl -s https://fluent-ai-prod.azurewebsites.net/health | jq
```

## If even QA is too slow

Run **Promote to Production** with `skip_qa_check` ticked. It ships the commit
without a QA run — dev has already run it, by step 1 above, but nothing has
exercised it against production-shaped configuration.

It still requires the commit to be on `main` and its image to exist; the bypass
skips the QA evidence, not the requirement that production runs reviewed code.
It logs a warning naming you as the actor, and production's reviewer approval
still applies — a second person is looking at it.

> [!CAUTION]
> Every use of `skip_qa_check` is something to raise at the incident review. If
> it is being used routinely, the QA step is too slow and that is the thing to
> fix.

> [!IMPORTANT]
> Migrations run before the deploy, from the commit being deployed. A hotfix
> that includes a migration will apply it to production before the new image is
> live — make sure the *currently running* build tolerates the new schema, or
> you have extended the outage rather than ended it.
