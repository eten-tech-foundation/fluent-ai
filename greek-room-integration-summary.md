# Greek-Room Integration — Architecture Review Summary

**Purpose:** Seeking high-level approval on the architectural approach before detailed design review.

## What's being proposed

Wrap Greek-Room's *Repeated Words* check as Fluent-AI's first AI-tool integration, using a pattern designed for every future tool (LLM drafting, embeddings, fine-tuning) — most of which will be slower and harder than this one.

## Core architectural decisions for review

1. **Tool-namespaced URLs** with **flat per-tool endpoints**: `POST /tools/{family}/{tool-name}` — e.g. `/tools/greek-room/repeated-words`. Mounted under `app/api/v1/endpoints/` to inherit the project's versioning trajectory. The natural alternative — a single dispatch endpoint like `POST /tools/dispatch` that takes `{"tool": "...", "params": {...}}` — was considered and rejected because it collapses the type system at the wire boundary (OpenAPI schemas degrade to `dict[str, Any]`, callers need external docs to know payload shapes, per-tool observability is lost). An MCP-style facade can still be layered on later without invalidating the per-tool URLs.

2. **Minimal `Tool` protocol with self-registration**: each tool is one file (`name`, `request_schema`, `response_schema`, `async execute()`). Auto-discovery walks the tool package at startup. Adding a future tool = drop a file, no central manifest to edit.

3. **Job-shaped response envelope from day one** — every endpoint returns `{job_id, tool, status, result, error, created_at, completed_at}`. Status is one of `queued|running|completed|failed|cancelled`. This lets us absorb an async job queue later without breaking callers.

4. **Reuse existing Fluent-AI substrate**: `X-API-Key` auth, `FluentAIException` hierarchy (one new subclass: `ToolExecutionException` → 502), structured logging, `lifespan` startup, API-key ownership model.

## The one open decision to be made

**Job execution model — Option A or Option B?**

- **Option A — Lightweight now**: Run synchronously via `asyncio.to_thread`. Smaller PR. Queue gets built later when a slow tool needs it. Risk: that "later" tends to slip into a slow tool's deadline.

- **Option B — Queue from day one**: Add `ai.tool_jobs` table + in-process worker + polling endpoints (`GET /jobs/{id}`). ~2–3× the work, but the substrate is ready for every slow tool that follows. Greek-room serves as the easy proving ground.

Both options ship the same external contract; they differ only in what's behind it.

## Explicitly out of scope (deferred)

Rate limits, request-size limits, pagination, MCP facade, SSE/WebSocket streaming, job retry policies, scheduled runs, multi-tenant fairness.

## Areas where input would be most valuable

1. Thoughts on the URL layout and the choice of per-tool endpoints over a single dispatch endpoint.
2. Thoughts on the `Tool` protocol + auto-registration pattern.
3. Thoughts on the job-shaped response envelope as the universal contract.
4. A preference between Option A and Option B (or a deliberate decision to defer).
