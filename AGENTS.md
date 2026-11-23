# AGENTS.md — Fluent AI

Fluent's AI service: a FastAPI app with a background worker for AI jobs, on Python 3.14. Only
[fluent-api](https://github.com/eten-tech-foundation/fluent-api) calls it, with an API key.

## Read only what the task needs

- Finding where an endpoint, job or service lives, or what it calls:
  [docs/code-map.md](docs/code-map.md).
- Changing API keys, AI jobs, what reaches a model provider, text-to-speech or the Greek Room
  check: [docs/domain-rules.md](docs/domain-rules.md).
- Adding a module, a table or a migration: [docs/architecture.md](docs/architecture.md).
- Setup, `fai.sh` commands and what CI runs: the [README](README.md#checks-before-a-pr).

Before you finish, run what CI runs: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy .`, `uv run pytest` and `./scripts/check-docs-structure.sh`. CI runs them with uv,
outside any container, and they run the same way on the host. pytest needs no database, only
`DATABASE_URL`, `API_BASE_URL` and `API_SERVICE_KEY` set, from `.env` or as dummy values.
`./fai.sh lint`, `format:check`, `typecheck` and `test` run the first four inside the AI
container. If the change adds or moves a module or an endpoint, update `docs/code-map.md`, and if
it changes a behavior that `docs/domain-rules.md` describes, update the rule in the same PR.

## Docs

See `docs/README.md` for the docs directory convention. Brainstorming and
writing-plans skill output goes to `docs/features/<slug>/`
(`proposal.md`/`design.md`/`plan.md`/`tickets/`), not the skill's built-in
`docs/superpowers/...` default.

## Agent skills

### Issue tracker

Issues are tracked as GitHub issues in this repo (via `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`CONTEXT.md` + `docs/adr/` at repo root). See `docs/agents/domain.md`.
