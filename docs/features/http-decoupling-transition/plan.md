# Transition Plan — HTTP-only decoupling from `fluent-api` (AI side)

**Audience:** the developer working the decoupling ticket in `fluent-ai`.
**Status:** approved design, ready to implement.
**Companion doc:** `fluent-api/docs/http-decoupling-transition.md` (the API-side half).

## Why this change

Today `fluent-ai` is coupled to `fluent-api` through a **shared PostgreSQL
database** rather than a network contract:

- The worker (`src/app/worker/suggestion_processor.py`) polls
  `ai.ai_suggestion_jobs` — a queue that `fluent-api` fills by
  **cross-schema INSERT**.
- The worker **reads `public` tables** owned by the platform
  (`bible_texts`, `books`, `languages`, `projects`, `project_units`,
  `translated_verses`) through read-only ORM models in
  `src/app/internal/platform_models.py` and `src/app/internal/project.py`,
  using a `role_ai_reader` grant.
- The worker **writes results** into `ai.ai_suggestions`, which `fluent-api`
  then reads cross-schema to serve clients.

This means the AI service can only run against the platform's database, and a
column rename on either side can silently break the other.

### Target

The **only** communication between the two services is HTTP. `fluent-ai`:

1. **Receives work** via an HTTP request from the API (instead of polling a
   shared table).
2. **Pulls the data it needs** from the API over HTTP (instead of cross-schema
   reads).
3. **Pushes results** to the API over HTTP (instead of writing a shared table
   the API reads).

```
   ┌─────────┐  (1) POST /suggestions  → 202     ┌─────────┐
   │ fluent  │ ────────────────────────────────► │ fluent  │
   │  -api   │                                    │  -ai    │
   │         │ ◄──── (2) GET context (HTTP) ───── │ worker  │
   │         │ ◄──── (3) POST results (HTTP) ──── │         │
   └─────────┘                                    └─────────┘
```

After this change, `fluent-ai` no longer needs any access to the `public`
schema, and may even run against its own database.

## Decisions already made (do not re-litigate)

| Topic | Decision |
| --- | --- |
| Translation-memory retrieval | **Moves to the API.** The API runs the hybrid FTS + proximity query (it owns `bible_texts` / `translated_verses`) and returns ready-to-use context to AI. AI stops doing this SQL. |
| How AI receives work | The **API triggers AI over HTTP** (API-side pg-boss job → HTTP call). AI exposes a trigger endpoint and enqueues into its own queue. |
| AI's queue | AI keeps a **general-purpose job table in its own (`ai`) schema** — not suggestion-specific. It should support job types beyond AI suggestions. |
| Existing AI data | **Greenfield** — `ai.ai_suggestions` / `ai.ai_suggestion_usage_log` move to API ownership and can be dropped here. No backfill. |

## Scope of AI-side work

1. Add a **trigger endpoint** + generalize the job queue.
2. Replace the worker's cross-schema **reads** with HTTP **pulls** from the API.
3. Replace the worker's result **writes** with an HTTP **push** to the API.
4. Add the **outbound HTTP client + service auth** to call the API.
5. Delete the cross-schema models, the result tables, and the platform DB role
   dependency.

---

### Workstream 1 — Trigger endpoint + generalized job queue

The API will stop inserting into `ai.ai_suggestion_jobs`. Instead it POSTs the
job spec to AI. AI accepts it and enqueues into its own table.

- **New endpoint.** Add `POST /suggestions` (or `POST /jobs`) under
  `src/app/routers/` or `src/app/api/v1/endpoints/`. Body matches the current
  job rows: `{ projectUnitId, bibleId, bookCode, chapterNumber, verseStart,
  verseEnd }` (accept a list to preserve the API's current batch-enqueue
  behavior). Guard it with the existing `require_api_key` dependency
  (`src/app/security/auth.py`) — the API will send `X-API-Key`.
- The handler **inserts a row into the job table and returns `202 Accepted`**
  immediately. It does **not** process inline — the existing worker loop picks
  it up. This keeps the request fast and preserves the worker's concurrency
  control.
- **Generalize the queue.** Per the queue decision, evolve
  `ai.ai_suggestion_jobs` (model in `src/app/models/ai_suggestion.py`) into a
  general `jobs` table that can carry other job types later. Suggested shape:
  - `id`, `job_type` (e.g. `"suggestion"`), `payload` (JSONB — holds
    `projectUnitId` / verse range etc.), `status`
    (`queued|processing|completed|failed`), `retry_count`, `error_message`,
    `created_at`, `updated_at`.
  - Preserve the **dedup unique constraint** semantics. Today it's
    `uq_ai_jobs_range` on the verse-range columns; with a JSONB payload, either
    keep a generated/expression unique index over the suggestion fields or add
    an explicit `dedup_key` text column the trigger handler computes. **This
    matters** — it is what makes a duplicated/replayed HTTP trigger harmless
    (see reliability note below).
  - Keep `idx_ai_suggestion_jobs_status_created` (rename to the generic table)
    so the `SELECT ... WHERE status='queued' ORDER BY created_at FOR UPDATE
    SKIP LOCKED` claim stays efficient.
  - Alembic migration to create/rename the generalized table.
- The worker loop (`worker_loop` in `suggestion_processor.py`) stays almost
  identical — it still claims `status='queued'` jobs with `FOR UPDATE SKIP
  LOCKED`. Add a `job_type` switch so it dispatches `"suggestion"` jobs to the
  existing `process_job` pipeline (and future types elsewhere).

### Workstream 2 — Pull inputs over HTTP (kill cross-schema reads)

`process_job` currently does three things against `public` tables. All three
move behind a single API call.

The API will expose `POST /internal/suggestion-context` (see API doc) that,
given the job's verse range + `projectUnitId`, returns in one response:

- the **source verses** in range (replaces the `BibleText`/`Book` query at the
  top of `process_job`);
- the **translation-memory context verses** (replaces
  `src/app/services/context_retrieval.py` and its FTS/proximity SQL — this
  logic is **moving into the API**);
- the **target language name** (replaces `_resolve_target_language_name`).

Changes:

- Add an **API HTTP client** (e.g. `src/app/core/api_client.py` or
  `src/app/services/platform_client.py`) using `httpx.AsyncClient`, reading
  base URL + service key from `config.py`/`Settings`. It calls the API's
  `/internal/*` endpoints with the **AI→API service key** (see WS4 auth).
- In `process_job`, replace Steps 1–3 (verse fetch, context retrieval, language
  resolution) with **one call** to the context client. The shape of
  `context_verses` returned must match what `TranslateRequest` /
  `VerseToTranslate` expect, and the verse-id format
  (`{book_code}_{chapter}_{verse}`) must be preserved so Step 5's parsing
  (`int(item.verse_id.split("_")[-1])`) still works.
- **Coordinate the contract** with the API dev before coding — the API is
  porting your `context_retrieval.py` logic, so agree on field names, the
  context-verse dict shape, and the `MAX_CONTEXT_VERSES_TOTAL` limit.
- `src/app/services/context_retrieval.py` is **deleted** here once the API
  serves context (it's being reimplemented API-side against the data it owns).

### Workstream 3 — Push results over HTTP (kill cross-schema write)

Step 5 of `process_job` currently upserts into `ai.ai_suggestions`. Replace it
with an HTTP POST to the API's `POST /internal/ai-suggestions`.

- Build the batch payload from `result.translations`:
  `{ items: [{ bibleTextId, projectUnitId, suggestedText, modelInfo }] }`
  (same fields the upsert uses today). The API owns the `ai_suggestions` table
  now and performs the upsert.
- **Reliability — important.** The job is only `completed` **after the API
  acknowledges** the result POST. If the POST fails, fall through to the
  existing `except` block so `retry_count` increments and the job re-queues —
  exactly the retry machinery already in `process_job`. This makes result
  delivery **at-least-once**; the API's result endpoint must be idempotent (it
  is — keyed on `(bibleTextId, projectUnitId)`), so a retried POST is safe.
- The `AiSuggestion` ORM model and the `ai.ai_suggestions` table are **removed
  from `fluent-ai`** (the API owns them now). Same for `AiSuggestionUsageLog` —
  usage logging is entirely an API concern and AI never touched it for reads.

### Workstream 4 — Outbound HTTP client & service auth

Two directions of auth now exist:

- **API → AI** (the trigger): already covered — AI's `require_api_key`
  validates the `X-API-Key` the API sends. No new work beyond guarding the new
  trigger endpoint.
- **AI → API** (context pull + result push): **net-new.** AI must authenticate
  to the API's `/internal/*` endpoints. The API is adding a service-auth seam
  (a shared service key / bearer token). AI sends that key on every outbound
  call from the client in WS2/WS3.

Config:

- Add to `Settings` (`src/app/config.py` / `core/config.py`):
  `api_base_url`, `api_service_key` (the AI→API outbound key). Keep the
  inbound `X-API-Key` validation as-is.
- Recommend **two distinct keys**, one per direction, so each rotates
  independently. Confirm with the team.

### Workstream 5 — Delete the shared-DB dependency

Once 1–4 work end-to-end against a real API:

- Delete `src/app/internal/platform_models.py` and
  `src/app/internal/project.py` (the read-only `public` ORM models).
- Delete `src/app/services/context_retrieval.py`.
- Remove the `AiSuggestion` / `AiSuggestionUsageLog` models and their tables
  (Alembic downgrade/migration); keep only the generalized `jobs` table and
  `api_keys` in the `ai` schema.
- Remove the `role_ai_reader` / `public`-schema grant dependency. The debug
  endpoint `GET /projects/_verify-permissions` and the `/projects/*` read
  endpoints in `src/app/routers/projects.py` exist **only** to demonstrate
  cross-schema reads — delete them (and `crud/projects.py`,
  `schemas/projects.py`, the `Project` model) unless they serve another
  purpose. Confirm nothing else depends on them.
- After this, `fluent-ai` needs database access **only** for its own `ai`
  schema (jobs + api_keys). It can run against a separate database; update
  `README.md` / `AGENTS.md` "Operating Modes" to reflect that the platform DB
  is no longer required for the AI service to function (the shared-DB modes
  become optional/legacy).
- Job cleanup: the API's `clean-ai-jobs.ts` is being deleted. If the
  generalized `jobs` table needs pruning of old `completed`/`failed` rows, add
  that cleanup **here** (a small periodic task or a `fai.sh` maintenance
  command), since AI now owns that table.

---

## Suggested sequencing

1. **WS1** trigger endpoint + generalized queue — can land behind a flag while
   the old poll-the-shared-table path still works.
2. **WS2** consume the API context endpoint — start once the API dev has
   `/internal/suggestion-context` available (the long pole on their side).
   Keep cross-schema reads as a fallback until verified.
3. **WS3** push results to the API.
4. **WS4** wire the outbound client + service key (needed by WS2/WS3, do it
   alongside them).
5. **WS5** delete cross-schema models, result tables, and the platform role —
   only after the full HTTP path is verified in a shared environment.

## Open questions to resolve with the API dev / team

1. **Exact context contract.** You own the current retrieval logic that the API
   is porting. Pair on the request/response shape: verse-id format, context
   verse fields, and the `limit` (`MAX_CONTEXT_VERSES_TOTAL`) so the prompt
   builder is unchanged.
2. **One key or two?** Recommend two directional service keys. Confirm storage
   + rotation.
3. **Trigger payload granularity.** Single job vs batch list — agree with the
   API (their pg-boss worker batches verses today). Accept a list.
4. **Generalized job table shape.** Confirm the JSONB-payload + `dedup_key`
   approach vs keeping typed columns for the suggestion case. Either is fine;
   pick one and preserve dedup.
5. **Separate database?** Decide whether `fluent-ai` keeps living in the shared
   Postgres instance (own schema, no `public` grants) or splits to its own DB.
   The HTTP decoupling makes the split possible but doesn't require it.

## Definition of done (AI side)

- AI exposes an authenticated trigger endpoint and enqueues into its own
  generalized `jobs` table; the worker no longer depends on the API inserting
  rows.
- `process_job` pulls all inputs from the API over HTTP — no queries against
  `public` tables; `context_retrieval.py` deleted.
- `process_job` pushes results to the API over HTTP — no writes to
  `ai.ai_suggestions`; result delivery is at-least-once with the existing retry
  loop gating job completion.
- `internal/platform_models.py`, `internal/project.py`, the result ORM models,
  and the cross-schema read endpoints are removed; AI needs no `public`-schema
  grant.
- `README.md` / `AGENTS.md` updated to reflect HTTP-only integration.
