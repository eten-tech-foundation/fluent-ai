# AGENTS.md — Fluent AI

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
