# Dependabot PR workflow (Fluent AI)

Repeatable, tool-agnostic process for triaging and merging Dependabot PRs in **Fluent
AI**. Written for any coding agent, IDE assistant, or human contributor — not tied to
any single editor/IDE tooling. Priority: keep the service stable on **Python 3.14 /
FastAPI / SQLAlchemy(async) / Alembic**, managed by **uv**, and never merge a bump that
silently corrupts the `ai` schema or breaks the AI provider integrations
(`google-genai`, `greekroom`).

## Core principles

1. **Stability first**: never merge an update that breaks `ai`-schema migrations
   (Alembic/asyncpg), the FastAPI/Pydantic request-response contract, or the
   `google-genai` / `greekroom` provider integrations.
2. **Verified authors only**: only process PRs opened by `app/dependabot` or
   `dependabot[bot]`.
3. **Automated validation, containerized**: always validate against a real, disposable
   Postgres via `./fai.sh` (see [Validation via `fai.sh`](#validation-via-faish)) —
   never rely solely on mocked/SQLite-backed unit tests for DB-touching bumps.
4. **Targeted merges**: squash-merge Dependabot PRs into `develop` only through Dependabot
   itself. Agent-authored fixes (e.g. a `uv.lock` regeneration, an Alembic autogenerate
   fixup) go out as their own small ticketed PR, never bundled into a bot PR.
5. **One merge at a time**: merge **one** PR, wait for `develop` CI to go green, then
   `@dependabot rebase` all other open bots in parallel before picking the next one.
   Stacking merges without rebasing risks a `uv.lock` that no longer resolves.
6. **Final-state validation**: after merging a batch, validate the fully merged `develop`
   branch — individual PRs can each pass while the combination breaks (e.g. a
   `sqlalchemy` bump plus an `alembic` bump that disagree on async driver behavior).
7. **Automate the queue**: an agent asked to "handle dependabot PRs" runs the full safe
   queue end-to-end without per-PR confirmation, stopping only to report blockers
   (failed CI, conflicts after rebase, risky/schema-affecting PRs).
8. **SHA-pin all GitHub Actions**: every `uses:` in `.github/workflows/*` must be pinned
   to a full 40-char commit SHA — never a floating tag (`@v4`) or branch ref. Tags are
   mutable and can be re-pushed by a compromised maintainer; a SHA pin freezes the exact
   commit that was reviewed. Dependabot's `github-actions` ecosystem understands SHA pins
   and will open PRs that bump the SHA (with the tag carried in a comment) so this stays
   maintainable. See [SHA pinning for GitHub Actions](#sha-pinning-for-github-actions).

## Categorization

| Category | Action | Example |
|----------|--------|---------|
| **Safe** | Validate via CI-first gate, then merge | `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `httpx`, `aiosqlite`, other dev-only tools; patch bumps of pure-Python utilities |
| **Risky** | Full local validation gate (containerized DB) mandatory | `fastapi`, `pydantic`/`pydantic-settings`, `sqlalchemy`, `asyncpg`, `alembic`, `google-genai`, `greekroom` |
| **Major/breaking** | Close with explanation, plan a dedicated upgrade ticket | Major version bump of `fastapi`, `sqlalchemy`, or `alembic`; any `python_requires`/`>=3.14` drift; coordinated multi-package bumps that change the async driver or migration engine |
| **CI-only** | Validate workflow syntax only — no app runtime impact | `.github/workflows/*` action SHA bumps (`actions/checkout`, `astral-sh/setup-uv`, `docker/*`, `azure/*`, etc.) — this is the ecosystem currently tracked in `.github/dependabot.yml`. All actions must be SHA-pinned (see [SHA pinning for GitHub Actions](#sha-pinning-for-github-actions)) |

Treat any package that touches the `ai` schema (SQLAlchemy models, Alembic migrations,
`asyncpg` driver) or an external AI provider client (`google-genai`, `greekroom`) as
**risky** by default, even on a patch bump — these are the packages most likely to
change wire-protocol or migration behavior silently.

## Validation via `fai.sh`

`./fai.sh` (or `fai.ps1` on Windows) is the only sanctioned way to run the validation
gate for Dependabot PRs. It builds the AI service image with the PR's `uv.lock` /
`pyproject.toml` and runs every check **inside the container**, against a **freshly
created, disposable Postgres container** — not a long-lived local DB, and not the
mocked/SQLite fixtures in `tests/conftest.py`. This is what makes `alembic upgrade
head` and real `asyncpg` round-trips part of the gate instead of being skipped.

### Standard validation sequence

Run this for **every** Dependabot PR before merge, safe or risky:

```bash
# 1. Fetch and check out the PR branch
git fetch origin pull/<PR_NUMBER>/head:dependabot-pr-<PR_NUMBER>
git checkout dependabot-pr-<PR_NUMBER>

# 2. Start a fresh, ephemeral stack (new pod/containers + new pgdata volume)
./fai.sh clean          # tear down any leftover containers/volumes from a prior PR
./fai.sh up              # rebuilds the AI image from this branch's uv.lock, starts DB + AI

# 3. Apply migrations against the fresh DB, then run the full check suite
./fai.sh db:init
./fai.sh format:check
./fai.sh lint
./fai.sh typecheck
./fai.sh test

# 4. Tear the ephemeral stack back down so the next PR starts clean
./fai.sh clean
```

- `./fai.sh clean` before `up` guarantees each PR is validated against a **brand-new**
  Postgres container and volume — no state (rows, migration history, roles) carried
  over from a previous PR's validation run.
- `./fai.sh up` rebuilds the `fluent-ai` image (`--build`/`podman build`) from the PR
  branch's `pyproject.toml` / `uv.lock`, so a bad dependency resolution or a broken
  `uv sync --frozen` fails fast at this step.
- `./fai.sh db:migrate` runs `alembic upgrade head` inside the container against the
  ephemeral DB — this is the step that catches `sqlalchemy`/`alembic`/`asyncpg` bumps
  that break migrations, which the mocked test fixtures cannot catch.
- `./fai.sh test` runs `uv run pytest tests/ -v` inside the AI container. Combined with
  the fresh containerized DB, this exercises real DB-backed paths, not just the
  SQLite/mocked-session fixtures under `tests/conftest.py`.
- `./fai.sh clean` after the run removes the pod/containers and the pgdata volume so
  nothing lingers for the next PR or the next contributor.

If `fai.sh` reports no container runtime (`podman` or `docker compose`), stop and
report it — do not fall back to running `uv run pytest` directly against a local/shared
Postgres, since that reintroduces the state-bleed and driver-mismatch risks this gate
exists to catch.

### Risky-PR additions

For PRs touching `fastapi`, `sqlalchemy`, `asyncpg`, `alembic`, `google-genai`, or
`greekroom`, add before `./fai.sh clean`:

```bash
./fai.sh db:history        # confirm the new revision chain is linear, no branch points
./fai.sh run uv run python -m app.db.seeds   # idempotent seed run against the fresh DB
```

and smoke-test the affected surface manually (e.g. hit a `greek_room` or `translations`
endpoint via `./fai.sh shell` → `curl localhost:8200/...`) if the bump touches request/
response schemas.

## SHA pinning for GitHub Actions

All `uses:` declarations under `.github/workflows/*` must be pinned to a **full 40-character
commit SHA**, not a mutable tag or branch ref:

```yaml
# REQUIRED — SHA-pinned, with the tag carried in a comment for readability
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
- uses: astral-sh/setup-uv@f94ec6bbd539c5c5ec5f4197533f056c4f9ea3c5 # v3.2.0

# FORBIDDEN — mutable tag refs (can be re-pushed by a compromised maintainer)
- uses: actions/checkout@v4
- uses: astral-sh/setup-uv@v3
```

### Why

- A tag (`@v4`) is a moving pointer. If the action's maintainer account is compromised,
  the attacker can move `v4` to a malicious commit and our next workflow run pulls it
  with no review. A SHA pin freezes the exact commit that was reviewed at PR time.
- This is a supply-chain hardening baseline, not a stylistic preference — it is the
  GitHub-recommended practice for `github-actions` workflows and is enforced by most
  security scanners (Scorecards, StepSecurity, OpenSSF).

### How Dependabot interacts with SHA pins

Dependabot's `github-actions` ecosystem natively understands SHA pins. When a workflow
uses `actions/checkout@<sha> # v4.2.2`, Dependabot opens a PR that bumps the SHA and
updates the trailing comment with the new tag — so pinning does not add manual toil.

### Reviewing a CI-only SHA-bump PR

1. Confirm the diff is **only** SHA changes (and the trailing tag comment) under
   `.github/workflows/*` — no `pyproject.toml`, `uv.lock`, or `src/` changes.
2. Confirm the new SHA matches the tag in the comment by checking the action's release
   page (e.g. `https://github.com/actions/checkout/releases/tag/v4.2.2`). Dependabot
   does this itself, but a 5-second sanity check on `azure/*` and `docker/*` actions is
   cheap insurance.
3. Trigger the workflow once on the PR branch (or rely on the Pre-Merge Validation run)
   to confirm the pinned versions still compose — a SHA bump can still break workflow
   syntax even when it does not touch app runtime.
4. No `fai.sh` gate is required — these PRs do not touch the `ai` schema, the FastAPI
   contract, or any Python dependency.

### Remediating an un-pinned action

If a Dependabot PR (or a manual review) surfaces an action still referenced by tag (e.g.
a newly added workflow that slipped in with `@v4`), **do not** fix it inside the
Dependabot PR. Open a separate small ticketed PR that converts the tag ref to a SHA pin
(with the tag carried in a comment), per the "Targeted merges" core principle. Once that
lands, Dependabot will keep the SHA current on its own schedule.

## Workflow

### 1. Triage

```bash
gh pr list --search "author:app/dependabot state:open" \
  --json number,title,mergeable,mergeStateStatus,statusCheckRollup,files
```

- If the author is not `app/dependabot` / `dependabot[bot]` → stop, do not process.
- Categorize per the table above (safe / risky / major / CI-only).
- Major/breaking bumps: close with a comment explaining why, and track in a dedicated
  upgrade ticket instead of merging.

### 2. Parallel rebase prep

Comment `@dependabot rebase` on every open bot PR that is `CONFLICTING`, has stale CI
(>24h), or isn't the PR about to merge. Skip PRs whose CI is already `IN_PROGRESS` from
a recent Dependabot push.

```bash
gh pr comment <PR_NUMBER> --body "@dependabot rebase"
```

### 3. Validate and merge (one at a time)

1. Run the [standard validation sequence](#standard-validation-sequence) (and the
   risky-PR additions if applicable).
2. For **safe** PRs where GitHub CI (Pre-Merge Validation workflow) is already fully
   green, the local `fai.sh` gate can be skipped — CI runs the same `ruff` / `mypy` /
   `pytest` checks. Still prefer the local containerized gate for anything touching
   `pyproject.toml` dependencies rather than only `uv.lock`.
3. Approve and merge:

   ```bash
   gh pr review <PR_NUMBER> --approve --body "CI green, fai.sh gate passed against ephemeral DB."
   gh pr merge <PR_NUMBER> --squash --delete-branch
   ```

4. Wait for `develop` CI (`Pre-Merge Validation` / equivalent post-merge checks) to go
   green: `gh run list --branch develop --limit 5`.
5. Immediately rebase all other open bots in parallel (step 2), then repeat from
   triage for the next green PR.

### 4. Final validation on `develop`

After merging one or more PRs, validate the fully merged state — not just the
individual PRs:

```bash
git checkout develop
git pull origin develop
./fai.sh clean
./fai.sh up
./fai.sh db:init
./fai.sh format:check
./fai.sh lint
./fai.sh typecheck
./fai.sh test
./fai.sh clean
```

### 5. Cleanup

```bash
git branch -D dependabot-pr-<PR_NUMBER>
```

## Handling issues

### Conflicts

Prefer `@dependabot rebase`. If manual resolution is required:

1. Do not blindly take "newer" for `fastapi`, `sqlalchemy`, `alembic`, `asyncpg` —
   check the Alembic revision chain isn't forked.
2. Re-run the full [standard validation sequence](#standard-validation-sequence)
   afterward.
3. Consider requesting explicit user approval before merging a manually resolved PR.

### `uv.lock` / resolution failures

If `./fai.sh up` fails to build because `uv sync --frozen` can't resolve:

1. This usually means a stacked merge went out without a rebase — regenerate with
   `uv lock` on a fresh branch from `develop`.
2. Open a small, separately ticketed fix PR (not bundled with a Dependabot PR).
3. Re-enforce the one-merge-then-rebase-all rule going forward.

### Migration failures

If `./fai.sh db:migrate` fails against the ephemeral DB on a Dependabot PR:

1. Do not merge.
2. Check whether the bump changed Alembic's autogenerate behavior or `asyncpg`'s
   connection/typing behavior against SQLAlchemy's async engine.
3. Share the failure with the user — schema-affecting dependency bumps should not be
   resolved unilaterally.

### Test / lint / typecheck failures

Do not merge. Share the `./fai.sh test` / `./fai.sh lint` / `./fai.sh typecheck` output
with the user.

## Reference

- Config: [`.github/dependabot.yml`](../../.github/dependabot.yml) (currently tracks
  the `github-actions` ecosystem; if a `pip`/`uv` ecosystem entry is added later, this
  workflow already covers it via the risky/safe categorization above).
- CI: [`.github/workflows/pre-merge.yml`](../../.github/workflows/pre-merge.yml)
- Container/runtime commands: [`AGENTS.md`](../../AGENTS.md), [`fai.sh`](../../fai.sh)
- Database ownership model: `AGENTS.md` → "Database Ownership" (this service owns only
  the `ai` schema; migrations run against the ephemeral DB never touch `public`,
  `pgboss`, or `drizzle`).
- SHA-pinning policy: see [SHA pinning for GitHub Actions](#sha-pinning-for-github-actions)
  above. All `uses:` declarations under `.github/workflows/*` are pinned to full 40-char
  commit SHAs (with the tag carried in a trailing comment). Dependabot's `github-actions`
  ecosystem is configured in `.github/dependabot.yml` to group all action SHA bumps into a
  single weekly PR (`groups.github-actions`) so the pins stay current without per-action
  PR noise.
