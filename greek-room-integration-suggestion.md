# Architecture Pitch — Bible Translation Tools in Fluent-AI

**Subject:** Wrapping Greek-Room (starting with the *Repeated Words* check) inside the Fluent-AI FastAPI service, in a way that establishes the platform's reusable pattern for all future AI-tool integrations.

**Status:** Draft for architectural approval. No code has been written; this document captures the design decisions that should be locked in before implementation begins.

**Audience:** Fluent-AI designer / architecture owner.

---

## 1. Executive Summary

Fluent-AI exists to provide AI services to the Fluent ecosystem. Greek-Room's *Repeated Words* check is the first of what will be a growing collection of those services — some fast (regex-based linguistic checks), most slow (LLM-based translation drafting, embedding generation, model fine-tuning). The integration of this first tool is therefore an opportunity to set the pattern that every subsequent tool will follow.

This pitch proposes:

1. A **tool-agnostic API contract** under `/tools/{family}/{tool-name}` (e.g. `POST /tools/greek-room/repeated-words`), placed under `app/api/v1/endpoints/` so it inherits Fluent-AI's existing versioning trajectory.
2. A **minimal `Tool` protocol** with **self-registering** implementations, so adding a new tool requires writing one file — no central manifest to maintain.
3. A **job-oriented response shape** (status + result envelope) chosen so the API can absorb an asynchronous job queue later without breaking callers.
4. Two clearly-articulated **execution-model options** — *Lightweight-now* (synchronous with async-shaped contract) and *Queue-from-day-one* (generic `tool_jobs` substrate) — for the designer to pick between deliberately, given that a job queue is almost certainly unavoidable in the long run.
5. **Reuse of Fluent-AI's existing infrastructure**: `X-API-Key` authentication, structured logging, the typed exception hierarchy, the API-key ownership model (user vs. org), and the `lifespan` startup pattern.
6. A flat, per-tool URL structure (one typed endpoint per tool) rather than a generic dynamic-dispatch endpoint — preserving per-tool OpenAPI documentation, type-safe Pydantic validation, and per-path observability.

The result is a small first PR that ships one working endpoint, plus an architectural substrate that every future tool slots into with minimal additional design work.

---

## 2. Context

### 2.1 What Greek-Room provides

Greek-Room is a suite of Bible-translation linguistic-quality tools maintained by BibleNLP, published as the `greekroom` package on PyPI. The first tool we are integrating is the **Repeated Words** check (`greekroom.owl.repeated_words`), which flags consecutive duplicate words (e.g. `"the the"`, `"truly truly"`) and distinguishes legitimate repetitions (tracked in a bundled `legitimate_duplicates.jsonl` data file) from likely translation errors.

The check function is **pure and synchronous**: it takes a corpus of verses, runs regex-based detection per line, and returns a structured findings list. It does no network I/O, no database access, and no concurrency. Data files are loaded from the installed package's resource directory.

Greek-Room internally uses a JSON-RPC 2.0–shaped request/response envelope on its `check_mcp()` function. **This envelope is an implementation detail of greek-room's own API** and is not part of any external standard. Fluent-AI will not expose this envelope to its callers.

### 2.2 Where this fits in Fluent-AI

Fluent-AI already has:

- An `X-API-Key`–based authentication system with per-user / per-org ownership (`owner_user_id` XOR `owner_org_id` on the `ApiKey` model), an `is_active` flag, and an `expires_at` field. The `require_api_key` and `require_admin` dependencies handle this transparently.
- A typed exception hierarchy rooted at `FluentAIException` with status-code-aware subclasses (`ValidationException`, `AuthenticationException`, `AuthorizationException`, `NotFoundException`, `ConflictException`, `DatabaseException`, `ExternalServiceException`), each carrying a wire `code` constant from `ErrorCode`.
- Structured logging via `app.logging.utils.get_logger`, with request-id correlation middleware (`RequestIDMiddleware`) and a `LoggingMiddleware` already wired up.
- A FastAPI `lifespan` context manager in `main.py` that is the natural home for service initialization.
- A versioned-API directory at `app/api/v1/endpoints/`, with the existing `api_keys.py` as the reference pattern. The directory's `__init__.py` explicitly notes that legacy `app/routers/projects.py` is "pending migration" into this location — so the v1 directory is the stated target for new domain endpoints.
- A PostgreSQL database with the `ai` schema reserved for service-owned tables, Alembic migrations, and a separate `ai_user` read-only role for reading the platform's domain tables.

Fluent-AI does **not** currently have:

- Any precedent for JSON-RPC, MCP (Anthropic's Model Context Protocol, or any other), or dynamic-dispatch-by-body endpoints.
- A job queue, background-task framework, or async-work infrastructure of any kind.
- A "tools" namespace in the URL space or in the code layout.

This integration introduces the tools namespace; it deliberately does not introduce MCP or a generic protocol facade today.

### 2.3 Why this tool is a good first proof point

Greek-Room's *Repeated Words* check is fast (sub-second for typical request sizes, single-digit seconds for whole-Bible runs), stateless, and has a small, well-defined input/output contract. That makes it an ideal first customer for the architectural pattern: a forgiving workload that exercises authentication, schema validation, service-layer wrapping, error handling, and registration — without the operational complexity of a slow workload.

The expectation, however, is that *most* future tools will not be this forgiving. The architectural decisions made for this PR should be sized for the harder cases, not for this easy one.

---

## 3. Design Principles

These principles run through every section that follows. They are the through-line for the design's coherence.

### 3.1 The contract is the expensive thing; the implementation is the cheap thing

External callers commit to URL shapes, response schemas, and authentication patterns. Once a caller exists in the wild, those things are expensive to change. Implementations behind them — synchronous vs. asynchronous, in-process vs. external worker, Postgres-backed vs. Redis-backed — are comparatively cheap to swap. The design therefore invests heavily in getting the contract right today, while accepting that the implementation will evolve.

### 3.2 The platform is an AI-services platform

Fluent-AI's identity is the wrapping and exposure of AI services. Many of those services will be slow: LLM-based translation drafting, embedding generation over corpora, model fine-tuning. The first tool (greek-room *Repeated Words*) is unusually fast, but designing the platform around that fast tool's profile would under-serve every tool that follows. The contract anticipates slow work even when the first implementation can be fast.

### 3.3 Visible at the type level, hidden behind it

Every tool gets its own typed endpoint, its own typed request schema, its own typed response schema. Per-tool OpenAPI documentation, per-tool Pydantic validation, per-tool URL-level observability — these all follow from this principle. Dynamic-dispatch endpoints (one URL that switches on a body field) buy small code-size wins at the cost of making the API undiscoverable; we reject them.

### 3.4 Reuse the existing Fluent-AI substrate

The integration adds no new authentication mechanism, no new logging framework, no new exception base class, no new dependency-injection style. It composes with `X-API-Key`, `app.logging.utils`, `FluentAIException`, FastAPI's `Depends`, and the `lifespan` pattern that already exist. New abstractions are introduced only where the substrate genuinely lacks them.

### 3.5 Make adding tools cheap

Adding a future tool — whether a second greek-room check, a Gemini-based service, or something new — should be a small, additive change: write one or two files, drop them in a known directory, and the platform picks them up. No central manifest, no edits to the worker, no changes to routing tables. This is the primary justification for the `Tool` protocol + auto-registration design described in §6.

### 3.6 Pragmatism over premature limits

Request-size limits, abuse-prevention quotas, and similar guardrails are deliberately deferred. The first caller of this API is owned by the same team as the API itself; abuse is not a vector. Limits will be added in response to observed problems rather than imagined ones, because premature limits routinely become a friction source of their own.

---

## 4. API Contract

### 4.1 URL layout

All tool endpoints live under the namespace:

```
/tools/{family}/{tool-name}
```

For the first deliverable:

```
POST  /tools/greek-room/repeated-words
```

The router file lives at `app/api/v1/endpoints/greek_room.py` and is mounted by `app/api/v1/router.py` with `prefix="/tools/greek-room"`. This placement matches the project's stated migration direction (per the comment in `app/api/v1/endpoints/__init__.py`) and means that if/when Fluent-AI eventually enforces a global `/api/v1` URL prefix, every tool endpoint moves with it as a single coordinated change.

Each tool family lives under its own sub-prefix. Future families would mount alongside greek-room, for example:

```
POST  /tools/greek-room/script-analysis        # future greek-room check
POST  /tools/greek-room/usfm-check             # future greek-room check
POST  /tools/gemini/translate                  # future Gemini-backed tool
POST  /tools/embeddings/sentence-encode        # future embedding tool
```

URLs use kebab-case to match existing Fluent-AI convention (`/api-keys`, etc.). Code files use snake_case correspondingly (`greek_room.py`, `repeated_words.py`).

### 4.2 Why flat per-tool endpoints, and not a single dispatch endpoint

The natural alternative — a single `POST /tools/dispatch` endpoint that takes `{ "tool": "greek-room.repeated-words", "params": { ... } }` — is rejected. Dynamic-dispatch endpoints collapse the type system at the wire boundary: every caller must consult external documentation to know what payload shape any given `tool` value requires, OpenAPI schemas degrade to `dict[str, Any]`, and observability tooling loses per-tool granularity. This is the same anti-pattern that has historically afflicted generic SOAP-style "operation" endpoints. Flat per-tool endpoints preserve type information end-to-end.

A unified MCP-style or aggregated-protocol facade *can* be added later as an additional surface on top of the per-tool endpoints (using the tool registry from §6 as its source of truth), without invalidating any of the per-tool URLs. That option is left explicitly open; see §11.

### 4.3 Authentication and authorization

All tool endpoints require API-key authentication via the existing `X-API-Key` header, validated by `app.dependencies.require_api_key`. No new authentication mechanism is introduced.

- A valid, active, non-expired API key is required. The existing dependency handles missing-key (401), invalid-key (401), revoked-key (403), and expired-key (403) cases.
- The `ApiKey` record is attached to `request.state.api_key` by the existing flow and is available to the route handler if it needs to record ownership on a job row (see §5).
- Future permission-gated tools (e.g. an admin-only fine-tune trigger) can layer on top of `require_admin` or new permission strings without changing the contract for unprivileged tools.

### 4.4 Request schema (Repeated Words)

The request payload for `POST /tools/greek-room/repeated-words` is a typed Pydantic model. Field names use Python-friendly `snake_case`; greek-room's internal hyphenated keys (`"snt-id"`, `"lang-code"`) are an implementation detail of the service layer and are not exposed.

```python
class VerseInput(BaseModel):
    snt_id: str        # e.g. "GEN 1:1"
    text: str

class RepeatedWordsRequest(BaseModel):
    lang_code: str                 # ISO 639-3, e.g. "eng"
    lang_name: str                 # e.g. "English"
    project_id: str                # caller-supplied project identifier
    project_name: str              # caller-supplied human label
    verses: list[VerseInput]
```

No size limits are imposed in this iteration; see §3.6 and §11.

### 4.5 Response shape and the status envelope

The response of every tool endpoint follows the same outer envelope, so the contract is uniform across tools and across sync/async execution modes:

```python
class ToolJobResponse[ResultT](BaseModel):
    job_id: str                              # always present
    tool: str                                # e.g. "greek_room.repeated_words"
    status: Literal["queued", "running", "completed", "failed"]
    result: ResultT | None = None            # populated when status == "completed"
    error: ToolError | None = None           # populated when status == "failed"
    created_at: datetime
    completed_at: datetime | None = None
```

In the Lightweight-now execution model (§5, Option A), every response is returned synchronously with `status == "completed"` and `result` non-null. In the Queue-from-day-one model (§5, Option B), the POST returns `status == "queued"` or `"running"` and the caller polls for completion. **Callers should always inspect `status` before reading `result`** — that single discipline keeps them forward-compatible across both models.

### 4.6 Result schema (Repeated Words)

The `result` field, when present, contains a flattened, Fluent-AI-native shape that hides greek-room's JSON-RPC envelope entirely:

```python
class RepeatedWordsFinding(BaseModel):
    snt_id: str                  # e.g. "GEN 1:1"
    repeated_word: str           # e.g. "in in"
    surf: str                    # exact surface text as it appeared
    start_position: int          # 0-based character offset within the verse
    legitimate: bool             # true if matched a legitimate-duplicate entry
    severity: float              # 0.1 (legitimate) or 0.5 (suspicious)

class RepeatedWordsSummary(BaseModel):
    total_findings: int
    legitimate_count: int
    verse_count: int

class RepeatedWordsResult(BaseModel):
    lang_code: str
    tool: str = "GreekRoom"
    check: str = "RepeatedWords"
    findings: list[RepeatedWordsFinding]
    summary: RepeatedWordsSummary
```

This shape is designed so that **pagination can be added later** as a non-breaking enhancement: a future `?page=N&page_size=M` query param would supplement `findings` with an optional `pagination` metadata object without renaming the field or changing existing behaviour for callers that don't pass paging parameters.

### 4.7 Job polling (only relevant under Option B)

If the designer selects Option B (Queue-from-day-one), the contract also includes a polling endpoint:

```
GET     /jobs/{job_id}            # return current status + result if ready
GET     /jobs?status=...&tool=... # list the caller's own jobs
DELETE  /jobs/{job_id}             # cancel a queued/running job (best-effort)
```

`GET /jobs/{job_id}` returns the same `ToolJobResponse` envelope shape, so a tool-specific endpoint and the generic polling endpoint serve identical payloads. The polling endpoint lives at `/jobs/` (sibling to `/tools/`), not nested under `/tools/`, because jobs are cross-tool: a single endpoint can return a Gemini job, a greek-room job, or any other tool's job equivalently.

### 4.8 Job ownership and visibility

A job is owned by the `(owner_user_id, owner_org_id)` pair derived from the API key that created it (the existing `ApiKey` model enforces exactly one of those being non-null per key). Visibility follows that ownership:

- A job created by a user-owned key is visible to any active key with the same `owner_user_id`.
- A job created by an org-owned key is visible to any active key with the same `owner_org_id`.
- Cross-bucket access (a user-owned key trying to see an org-owned key's job) is denied in this iteration; richer user-belongs-to-org relationships are out of scope.
- An API key with the `admin` permission can see any job, for support and debugging workflows.

This policy is recorded with each job in the `tool_jobs` row, so subsequent polls remain authorized even if the originating key is later revoked. The structured logger captures `api_key_id` on each job-write, giving Fluent-AI a built-in audit trail of "who ran what when" without a separate audit table.

---

## 5. Job Execution Model — The Central Decision

This is the most important architectural decision in the document, and the one the designer should consciously choose between rather than defaulting into. Both options use the same outer API contract (§4.5); they differ only in what happens behind it. The choice is **when** to build the job-queue substrate, not **whether** to build it.

### 5.1 Why this decision matters

Fluent-AI is, by its own positioning, an AI-services platform. Most AI workloads — model fine-tuning, large-corpus embedding generation, batched LLM translation drafting — run for tens of seconds to hours. Returning those synchronously over HTTP is impractical: connections idle out at upstream proxies (NGINX, ALB, Cloudflare are typically 60s), retries get expensive, and the caller's UI cannot let the user navigate away. **A job queue is, with very high probability, unavoidable in the long run.**

The first tool, *Repeated Words*, does not need a queue on its own merits. A whole-Bible run takes only a few seconds of CPU. But the platform that hosts this first tool will host many more, most of which will need a queue. The decision is whether to use the first easy tool as the proving ground for the queue substrate (Option B), or to ship the first easy tool quickly and add the queue when a tool that genuinely needs it arrives (Option A).

### 5.2 Option A — Lightweight-now, queue-shaped contract

**Implementation:** The route handler runs the greek-room check synchronously, offloading the CPU-bound work to a worker thread via `await asyncio.to_thread(...)` to keep the event loop responsive. No database table for jobs is introduced. The response is constructed with `status: "completed"` and the result inline.

The polling endpoint (`GET /jobs/{job_id}`) may either be omitted entirely or stubbed to always return 404; the `job_id` returned by the POST is a single-use identifier with no server-side persistence in this option.

**What this requires building:**

- Pydantic schemas for request, response envelope, and result body.
- A `RepeatedWordsService` class (see §7) that wraps `greekroom.owl.repeated_words.check_mcp` behind `asyncio.to_thread`.
- The route handler.
- The `Tool` protocol and self-registration mechanism (§6) — built once, reused by every future tool.
- The `ToolExecutionException` addition to the exception hierarchy (§8).
- Eager `RepeatedWordsService` construction in `lifespan` (§10).
- Unit tests and an integration test that submits a sample request.

**Pros:**

- Smallest scope; fastest to ship.
- No new database migrations, no new background-task infrastructure, no worker process to monitor.
- Greek-room's typical response time (milliseconds to a few seconds) is well within HTTP timeout budgets, so users will not feel the absence of a queue.
- The queue-shaped contract means callers written against Option A continue to work unmodified if/when Option B is layered in later.

**Cons:**

- Every later tool that genuinely needs a queue will have to introduce it. Greek-room misses its chance to be the proving ground.
- Until the queue is added, large or slow tool invocations are at risk of HTTP-timeout failures.
- The first slow tool will likely raise the same questions this document raises again — possibly under time pressure.
- The synchronous path silently couples request fairness to FastAPI's thread pool size; one slow request can starve a small number of others during its run.

**When to choose Option A:** if the priority is shipping greek-room end-to-end this milestone with minimal architectural surface area, and the team is comfortable revisiting the job-queue question on a future PR when a slower tool's needs make the decision concrete.

### 5.3 Option B — Queue-from-day-one, greek-room as proving ground

**Implementation:** A new `tool_jobs` table is created in the `ai` schema, with columns for job identity, ownership, status, request payload, result payload, error, timestamps, and an optional progress field. Greek-room's route handler writes a row with `status: "queued"`, returns a 202 with `job_id`, and the actual work is performed by a worker that updates the row.

The worker mechanism is a separate, evolvable concern, layered as follows (each layer can be swapped without changing the API contract or the `tool_jobs` schema):

| Tier | Mechanism | Typical use |
|------|-----------|-------------|
| W1 | `asyncio.create_task` spawned per job inside the API process | Single replica, short jobs; lightest possible |
| W2 | A long-lived `asyncio` task started in `lifespan` that polls `tool_jobs` for `queued` rows | Same process, bounded concurrency, cleaner separation |
| W3 | A separate Python process (same Docker image, different entrypoint) polling the same DB, using PostgreSQL `FOR UPDATE SKIP LOCKED` for safe multi-worker coordination | Independent scaling, survives API restarts |
| W4 | An external broker (Redis or RabbitMQ) plus a worker framework (Celery, Arq, or Dramatiq) | Multi-host deployments, retry policies, scheduled jobs, real SLAs |

**For this PR, the recommendation is W1 or W2** (the designer should specify which). Both are appropriate for greek-room's workload and both leave the door open to W3/W4 without contract changes. W3 becomes worth the operational cost when the *second* slow tool arrives.

**What this requires building** (in addition to everything in Option A):

- Alembic migration adding `ai.tool_jobs`.
- SQLAlchemy model for `ToolJob` and CRUD functions.
- The polling endpoint(s) at `/jobs/{job_id}`, `/jobs`, and (optionally) `DELETE /jobs/{job_id}`.
- Job-scoping logic that enforces the ownership policy from §4.8.
- The worker mechanism itself (W1 or W2).
- A configurable TTL for completed/failed job rows (default proposal: 7 days), and a cleanup mechanism — either a periodic `asyncio` task in W1/W2, or simply a documented manual `DELETE FROM ai.tool_jobs WHERE ...` for now.
- Tests covering: submission, polling for queued/running/completed/failed states, cross-tenant isolation, admin-override visibility, and concurrent submission of multiple jobs.

**Pros:**

- The queue substrate is in place from day one; every future tool slots in by writing one service class and registering it.
- The API contract (status envelope, polling endpoint) is exercised by a real workload immediately, so its rough edges are found and fixed early.
- Long-running future tools (fine-tunes, embeddings, batches) inherit a working job system rather than being blocked on building one.
- The built-in audit trail (§4.8) is available from the start.

**Cons:**

- Roughly 2–3× the implementation work of Option A.
- A polling protocol for a tool that completes in milliseconds feels heavyweight for callers, and may invite anti-patterns like tight polling loops. (Mitigations are listed below.)
- The worker-tier choice (W1 vs. W2) is itself a small design call that the designer would need to make.
- Operational concerns appear earlier: stuck-jobs queries, restart recovery, TTL cleanup.

**Mitigation for the "polling feels heavyweight" concern.** A common pattern, used by Google Cloud's long-running operations API and Anthropic's batch API among others, is a synchronous-blocking convenience on the polling endpoint:

```
GET /jobs/{job_id}?wait=true&timeout=30s
```

The server blocks for up to `timeout` seconds, returning the final state if the job completes within that window or the current intermediate state otherwise. Fast jobs feel synchronous to the caller; slow jobs gracefully fall back to a normal poll loop. This keeps a single contract working well for both extremes and is a small addition under Option B.

**When to choose Option B:** if the team accepts the upfront cost in exchange for a substrate that every subsequent tool benefits from, and is willing to use greek-room as the easy first workload that proves the queue out before harder workloads arrive. This is the architecturally honest choice for an AI-services platform.

### 5.4 Recommendation framing

This document does not recommend one option over the other; both are legitimate and the right answer depends on the team's milestone constraints, headcount, and tolerance for revisiting infrastructure decisions later. What it does recommend is that the choice be made **explicitly**, with the trade-offs above visible, rather than by inertia.

A reasonable position is: *"Option A now, with a planned Option B follow-up before the first slow tool ships."* The risk to flag with that position is that "before the first slow tool ships" tends to slip, and the slow tool's deadline becomes the queue's deadline.

The opposite reasonable position is: *"Option B now, because we know we will build it anyway and greek-room is the easiest workload we will ever throw at it."* The risk to flag with that position is the additional implementation time and the modest operational complexity introduced before there is a real load case demanding it.

---

## 6. Tool Protocol & Self-Registering Tools

The same `Tool` protocol applies under both Option A and Option B. Under Option A it serves as the dispatch target the route handler calls; under Option B it serves as the dispatch target the worker calls when processing a queued job. In both cases, **adding a new tool requires writing one file** — no central list to edit.

### 6.1 The protocol

```python
from typing import ClassVar, Protocol, runtime_checkable
from pydantic import BaseModel


@runtime_checkable
class Tool[RequestT: BaseModel, ResultT: BaseModel](Protocol):
    name: ClassVar[str]                       # e.g. "greek_room.repeated_words"
    request_schema: ClassVar[type[BaseModel]]  # the Pydantic request model
    response_schema: ClassVar[type[BaseModel]] # the Pydantic result model

    async def execute(self, request: RequestT) -> ResultT: ...
```

The protocol is intentionally minimal. Any tool — fast or slow, in-process or HTTP-backed, pure-Python or LLM-driven — implements these four members. The interface is a deliberate floor, not a ceiling; richer concerns (streaming, progress reporting, cancellation) are layered on later via optional methods or sub-protocols when a tool that actually needs them appears. Predicting those concerns now would risk a protocol that is wrong for the second tool, which is a worse failure mode than the small refactor required to widen the protocol later.

**Optional lifecycle hooks.** Tools that need heavy initialization (loading data files, opening client connections) or graceful cleanup may *additionally* implement `async def startup()` and `async def shutdown()`. These are not part of the required protocol — a tool whose `__init__` is sufficient simply omits them — but the lifespan code in §10 calls them via a `hasattr` check when present, so registered tools that do declare them get their hooks invoked at the right moments. This keeps the required surface small while allowing tools with real lifecycle needs to opt in without ceremony.

### 6.2 The registry

A single module — proposed as `app/services/tool_registry.py` — holds a dict mapping `tool.name` to the tool instance, plus a `register()` helper:

```python
_REGISTRY: dict[str, Tool] = {}

def register(tool: Tool) -> Tool:
    if tool.name in _REGISTRY:
        raise RuntimeError(f"Duplicate tool registration: {tool.name}")
    _REGISTRY[tool.name] = tool
    return tool

def get(name: str) -> Tool:
    if name not in _REGISTRY:
        raise NotFoundException(message=f"Tool '{name}' is not registered.")
    return _REGISTRY[name]

def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())
```

### 6.3 Self-registration

Each tool's module registers its instance at import time:

```python
# app/services/greek_room/repeated_words.py
class RepeatedWordsService:
    name = "greek_room.repeated_words"
    request_schema = RepeatedWordsRequest
    response_schema = RepeatedWordsResult

    async def execute(self, request: RepeatedWordsRequest) -> RepeatedWordsResult:
        ...

tool_registry.register(RepeatedWordsService())
```

For self-registration to actually take effect, the tool modules must be **imported** somewhere during app startup; otherwise their registration code never runs. Two viable mechanisms:

- **Explicit imports in `app/services/__init__.py`.** Simple, robust, but reintroduces a central list — partially defeating the self-registration goal.
- **Automatic package discovery during `lifespan`.** Use `pkgutil.iter_modules` (or `importlib.resources` / `importlib.import_module`) to walk known namespaces (`app.services.greek_room`, future `app.services.gemini`, etc.) and import every submodule. About ten lines of code. True "drop a file, it registers itself" behaviour. Recommended.

The discovery walk runs once at startup, inside `lifespan`. After that, the registry is read-only for the lifetime of the process. Discovery failures are fatal at boot, with the logger reporting which tool module failed to import — consistent with the fail-fast-at-startup principle from §10.

### 6.4 What the registry enables

- **The route handlers stay thin.** A tool endpoint validates the request via Pydantic, calls `tool_registry.get("greek_room.repeated_words").execute(request)`, returns the response envelope. No tool-specific code in the routing layer.
- **The worker (under Option B) stays generic.** When processing a queued row, it reads the row's `tool_name`, looks up the tool, validates the stored request payload against `request_schema`, calls `execute`, and writes the result back. The same worker code handles every tool.
- **Cross-cutting tooling becomes trivial.** A `GET /tools` discovery endpoint can list registered tools and their schemas from the registry. A future MCP-style or aggregated-protocol facade can iterate the registry as its source of truth. An admin diagnostics page can show "tools loaded" at runtime.
- **Tests can register a fake tool.** Unit tests can install a mock `Tool` into the registry to exercise the route/worker plumbing without needing real greek-room data files.

---

## 7. Module and File Layout

The integration adds the following files. Each is small and focused, which suits both human review and AI-assisted editing.

### 7.1 New files (both options)

```
src/app/
├── api/v1/
│   ├── router.py                              # MODIFIED: include greek_room router
│   └── endpoints/
│       └── greek_room.py                       # NEW: route handlers
├── schemas/
│   ├── greek_room.py                           # NEW: Pydantic request/response models
│   └── tool_job.py                             # NEW: generic ToolJobResponse[ResultT] envelope
├── services/
│   ├── tool_registry.py                        # NEW: protocol + registry + auto-discovery
│   └── greek_room/
│       ├── __init__.py                         # NEW: package marker
│       └── repeated_words.py                   # NEW: RepeatedWordsService
├── errors/
│   ├── codes.py                                # MODIFIED: add TOOL_EXECUTION_ERROR
│   └── exceptions.py                           # MODIFIED: add ToolExecutionException
└── main.py                                     # MODIFIED: lifespan loads registry + service
```

The generic `tool_job.py` schema module is shared by every tool family — its `ToolJobResponse[ResultT]` envelope is the single contract that wraps each tool's typed result. Tool-specific schemas (request and result bodies) live alongside the tool family in `schemas/greek_room.py`, `schemas/gemini.py`, etc.

The `services/greek_room/` package is structured to **scale horizontally**: when a second greek-room tool (e.g. script analysis) is added, it gets its own sibling module (`services/greek_room/script_analysis.py`) and registers itself. No existing file changes. When a non-greek-room tool family arrives (e.g. Gemini-backed translation), it gets its own sibling package (`services/gemini/`) at the same level.

### 7.2 Additional files under Option B (Queue-from-day-one)

```
src/app/
├── api/v1/endpoints/
│   └── jobs.py                                 # NEW: polling endpoints
├── models/
│   └── tool_job.py                             # NEW: SQLAlchemy ToolJob model
├── crud/
│   └── tool_jobs.py                            # NEW: queries for jobs
├── services/
│   └── tool_jobs.py                            # NEW: high-level job lifecycle
├── workers/                                    # NEW package (if W1/W2 in-process worker)
│   ├── __init__.py
│   └── tool_worker.py                          # in-process polling worker
└── db/migrations/versions/
    └── <date>_create_ai_tool_jobs.py           # NEW: Alembic migration
```

If the designer selects W3 (separate worker process), the `workers/` package gains an entry point exposed via a CLI shim (e.g. `fai.sh worker`) and the Dockerfile gains a corresponding optional command.

### 7.3 Tests

Tests mirror the source layout, consistent with the existing `tests/api/v1/` structure:

```
tests/
├── api/v1/
│   ├── test_greek_room.py                      # NEW: route-level tests
│   └── test_jobs.py                            # NEW (Option B only): polling tests
├── services/
│   └── greek_room/
│       └── test_repeated_words.py              # NEW: service-level tests
└── test_tool_registry.py                       # NEW: registry tests
```

Test coverage for the first iteration includes:

- A successful repeated-words check against a small canned corpus.
- Authentication rejection (no key → 401, bad key → 401, revoked key → 403).
- Pydantic validation rejection on malformed input.
- A `ToolExecutionException` is raised and surfaces as a clean 502 when the underlying greek-room call fails.
- The tool registry rejects duplicate registrations and resolves names correctly.
- (Option B only) Job submission → poll lifecycle, cross-tenant isolation, admin override.

---

## 8. Error Handling

Fluent-AI already has a mature exception hierarchy rooted at `FluentAIException`, with status-code-aware subclasses and wire `code` constants. The integration extends that hierarchy by exactly one class.

### 8.1 New exception: `ToolExecutionException`

```python
class ToolExecutionException(FluentAIException):
    """A tool implementation failed during execution.

    Distinct from generic 500s (unexpected platform errors) and from
    ExternalServiceException (HTTP-upstream failures); this signals that
    a tool's own execution did not complete successfully, for reasons
    internal to the tool but not the platform.
    """
    status_code = 502
    default_code = ErrorCode.TOOL_EXECUTION_ERROR
    default_message = "Tool execution failed."
```

And the corresponding entry in `app.errors.codes.ErrorCode`:

```python
TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
```

`ToolExecutionException` is **tool-agnostic** and intended for every future tool, not just greek-room. The `details` field carries the tool name and the underlying error description so operators have enough context to diagnose.

### 8.2 Mapping of failure modes

| Failure mode | Exception raised | HTTP status | Wire `code` |
|--------------|------------------|-------------|-------------|
| Pydantic validation fails on the request | FastAPI's built-in handling | 422 | `VALIDATION_ERROR` |
| Missing or malformed API key | `AuthenticationException` (existing) | 401 | `AUTHENTICATION_REQUIRED` |
| Revoked or expired API key | `AuthorizationException` (existing) | 403 | `AUTHORIZATION_DENIED` |
| Job ID in URL doesn't exist (Option B) | `NotFoundException` (existing) | 404 | `RESOURCE_NOT_FOUND` |
| Caller polls a job they don't own (Option B) | `NotFoundException` (existing) | 404 | `RESOURCE_NOT_FOUND` |
| Tool name not found in registry | `NotFoundException` (existing) | 404 | `RESOURCE_NOT_FOUND` |
| Greek-room's `check_mcp` raises | `ToolExecutionException` (new) | 502 | `TOOL_EXECUTION_ERROR` |
| Database write fails (Option B) | `DatabaseException` (existing) | 500 | `DATABASE_ERROR` |
| Unhandled exception | (global handler → 500) | 500 | `INTERNAL_SERVER_ERROR` |

Note the deliberate choice to return **404 rather than 403** when a caller polls a job owned by a different tenant. Returning 403 would leak the fact that the job exists, defeating the cross-tenant isolation. This is the same pattern the rest of Fluent-AI should follow for tenant-scoped resources.

### 8.3 Where exceptions are caught

The service-layer wrapper around greek-room uses a **tightly-scoped** `try/except` around just the third-party call — not a bare `except Exception` over the whole route. Other exceptions from request shaping, response serialization, or schema construction are allowed to propagate to the global exception handlers, which already produce well-formed `ErrorResponse` bodies.

Under Option B, tool failures inside the worker do **not** propagate to an HTTP response. Instead, the worker catches them and writes `status="failed"` plus an error object to the `tool_jobs` row. The subsequent `GET /jobs/{job_id}` then returns 200 OK with `status="failed"` and the error in the body. HTTP-level errors on the polling endpoint are reserved for problems with the *polling call itself* (auth, job-not-found), not for the underlying job's outcome.

### 8.4 Logging

Failures inside the service layer are logged with `logger.exception(...)` (capturing the stack trace via the existing structured logger) before being re-raised as `ToolExecutionException`. The original exception is preserved via `raise ... from e` for upstream tooling that wants the cause chain. The wire response, however, contains only safe-to-display fields — never raw stack traces or internal paths.

---

## 9. Dependency, Python Version, and Packaging Notes

### 9.1 The greek-room dependency

Greek-Room is added as a standard PyPI dependency:

```toml
# pyproject.toml
dependencies = [
    # ... existing ...
    "greekroom>=0.0.20",
]
```

This is the simplest path: reproducible via `uv.lock`, no git pinning, no editable-path complications, no special handling in Docker. The currently-released version on PyPI is `0.0.20` (alpha-stage), which is acceptable for the initial integration; if a fix needed by Fluent-AI is unreleased upstream, the dependency can be swapped to a git pin at that point — a small, contained change.

### 9.2 Transitive dependencies

Greek-Room itself pulls in:

- `regex` — high-performance Unicode regex (C extension).
- `unicodeblock` — Unicode block lookup.
- `uroman` — universal romanization library.
- `wheel` — packaging support.

The check function this integration uses (`greekroom.owl.repeated_words.check_mcp`) does not appear to exercise `uroman`'s heavier code paths, but `uroman` is still pulled into the dependency closure. If any of these are problematic to install on the target Python version, the implementer should surface that as a blocker before committing to the dependency choice.

### 9.3 Python version compatibility

Fluent-AI's `pyproject.toml` declares `requires-python = ">=3.14"`. Greek-Room declares `>=3.11`. The intersection is 3.14.

Python 3.14 is sufficiently new that wheel availability for some of greek-room's transitive C-extension dependencies (`regex` in particular) is not guaranteed. The implementer should verify with a smoke test before locking in the dependency:

```bash
uv sync --dry-run
uv run python -c "import greekroom; import greekroom.owl.repeated_words; print('ok')"
```

If wheels are unavailable, the realistic recourses are: (a) wait for upstream wheels, (b) enable in-Docker source compilation by adding `build-essential` to the image, or (c) lower fluent-ai's Python floor to a version with broader wheel coverage. The decision among these is out of scope for this pitch.

### 9.4 Data files

Greek-Room bundles its data file `legitimate_duplicates.jsonl` inside the installed package. A normal `pip` / `uv` install places it at the package's expected location and the library's data-discovery code finds it without any extra wiring. **No manual data file mounting, copying, or environment variable is required.**

The data file is approximately 1.4 KB today — small enough that loading it once at service startup imposes negligible cost. (Greek-Room's internal implementation actually re-reads it inside the check function, but that is a minor upstream inefficiency that does not affect correctness and is not worth working around.)

---

## 10. Lifespan, Dependency Injection, and Event-Loop Hygiene

### 10.1 Service initialization via `lifespan`

Each tool service (e.g. `RepeatedWordsService`) loads any heavy state — data files, model artifacts, client connections — once at startup, inside the FastAPI `lifespan` context manager. The service instance is stored on `app.state` and exposed to route handlers via a dependency function.

This achieves three things:

- **Fail-fast at startup.** A missing data file or a broken upstream connection surfaces in the boot logs, not as a mysterious 500 to the first caller.
- **Fast first request.** The cost of loading data files (or initializing AI client SDKs) is paid once, before traffic arrives.
- **Testability.** `app.dependency_overrides` lets tests substitute a fake or stub for the service without monkey-patching.

The pattern (illustrative, not prescriptive):

```python
# main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-discover and import tool modules so self-registration runs.
    tool_registry.discover("app.services.greek_room")  # and future families

    # Each registered tool may optionally declare startup/shutdown hooks.
    for tool in tool_registry.all_tools().values():
        if hasattr(tool, "startup"):
            await tool.startup()

    logger.info(
        "Tool registry loaded",
        tools=list(tool_registry.all_tools().keys()),
    )
    yield
    for tool in tool_registry.all_tools().values():
        if hasattr(tool, "shutdown"):
            await tool.shutdown()
```

```python
# dependencies.py
def get_tool(name: str):
    def _resolver() -> Tool:
        return tool_registry.get(name)
    return _resolver

# Usage in a route handler:
async def check_repeated_words(
    request: RepeatedWordsRequest,
    tool: Tool = Depends(get_tool("greek_room.repeated_words")),
    api_key: ApiKey = Depends(require_api_key),
) -> ToolJobResponse[RepeatedWordsResult]:
    ...
```

The `startup()` and `shutdown()` hooks are kept as optional protocol members (default no-op) precisely so tools like `RepeatedWordsService` that have heavy init can use them, while trivial tools can ignore them.

### 10.2 Event-loop hygiene

Greek-Room's `check_mcp` function is **synchronous and CPU-bound** (regex work over each verse). Calling it directly inside an `async def` handler would block the FastAPI event loop for the duration of the work, freezing all concurrent requests on the same worker.

The service-layer wrapper therefore offloads the call to a worker thread:

```python
class RepeatedWordsService:
    async def execute(self, request: RepeatedWordsRequest) -> RepeatedWordsResult:
        mcp_d, misc_data, _ = await asyncio.to_thread(
            repeated_words.check_mcp,
            self._build_jsonrpc_payload(request),
            self._data_filename_dict,
            repeated_words.new_corpus(self._make_id(request)),
        )
        return self._flatten(mcp_d, misc_data, request)
```

`asyncio.to_thread` is the standard, lightweight mechanism for keeping CPU-bound sync code from blocking the event loop. It scales adequately for greek-room's profile; if a future tool is so CPU-intensive that thread-pool contention becomes a real concern, the worker tier (W3 process-level worker) handles it more cleanly than threads anyway.

The same `asyncio.to_thread` discipline applies whether execution happens inline (Option A) or inside the job worker (Option B). Under W2 (an `asyncio`-loop-based worker), the discipline is identical. Under W3 (a separate process), the offload is implicit in the process boundary — but the worker entrypoint should still avoid blocking its own loop in case of mixed-workload futures.

### 10.3 Logging and request correlation

The existing `RequestIDMiddleware` and structured logger work transparently through `asyncio.to_thread` because they are based on `contextvars`, which are propagated across thread boundaries by `asyncio.to_thread` (and through tasks in general). No special handling is required for request-ID correlation to appear correctly in logs emitted from the threaded greek-room call.

Under Option B, jobs are decoupled from the originating request, so the polling response cannot inherit the original request ID directly. Each job's logs use the `job_id` as the correlation key instead, and the row records the `request_id` of the *submission* call separately for cross-referencing. This is a small but worth-knowing implementation detail.

---

## 11. Explicitly Out of Scope

These items are recognized, intentional non-goals for this iteration. They are listed here so that their absence in the implementation is a *decision*, not an oversight.

- **Request-size limits and abuse quotas.** Deferred per §3.6. To be added in response to observed problems.
- **Pagination on findings.** The result schema is designed to support it (§4.6), but no paging is implemented in this iteration.
- **Rate limiting.** No per-key or per-tenant rate limits are introduced. Same rationale as size limits.
- **Tool versioning at the URL level.** A future tool revision that breaks compatibility would introduce a new tool name (e.g. `greek_room.repeated_words.v2`) rather than mutating the existing one; this is consistent with the tool-registry being keyed by name.
- **MCP-style (Anthropic Model Context Protocol) facade.** A facade that surfaces the tool registry through an MCP server endpoint is feasible later — the registry exists exactly to make this kind of cross-cutting surface tractable — but the authentication story for MCP-to-Fluent-AI (how a remote MCP client authenticates as a Fluent-AI tenant) is non-trivial and is left for a dedicated future design.
- **Aggregated dispatch endpoint.** A single `POST /tools/dispatch` that takes a `tool` field is rejected per §4.2; an aggregated *batch* endpoint (run multiple tools on the same corpus) is plausible but not designed here.
- **Server-Sent Events / WebSocket streaming for job progress.** Long-running tools could benefit from streamed progress; this is a deliberate non-goal for v1. Polling with `?wait=` is the only async-progress mechanism in the v1 contract.
- **Job retry and dead-letter handling.** Under Option B, failed jobs are surfaced via `status="failed"` and the caller is responsible for resubmission. Automatic retry policies, exponential backoff, and dead-letter queues are out of scope.
- **Job cancellation semantics beyond "queued."** Under Option B, `DELETE /jobs/{id}` is best-effort cancellation: it can reliably cancel a `queued` job, may or may not cancel a `running` job depending on the worker tier, and is a no-op on terminal states.
- **Scheduled / cron-style tool runs.** Not part of v1.
- **Multi-tenant scheduling fairness.** All tenants share one worker pool in W1/W2. Per-tenant priority queues are a W4-era concern.

---

## 12. Open Questions for the Designer

These are the decisions this pitch deliberately leaves open. Each has a defensible recommendation in the body of the document; the designer should make each call consciously before implementation begins.

1. **Job execution model: Option A (Lightweight-now) or Option B (Queue-from-day-one)?** (§5)
2. **If Option B: worker tier W1 (per-job task) or W2 (long-lived poller task)?** Both are appropriate for greek-room; W2 is slightly more aligned with the future W3 process-level worker. (§5.3)
3. **Job ownership policy as described in §4.8 (per-tenant scoping by `owner_user_id` XOR `owner_org_id` + admin-permission override + 404 on cross-tenant access) — approved as written?** This was drafted from a reasonable default reading of the existing `ApiKey` model and was not separately ratified during the design conversation. (§4.8)
4. **The `tool_jobs` table shape sketched in §5.3 ("Option B — What this requires building") — approved as the starting schema, or are there columns to add/remove before the Alembic migration is written?** Particularly: do we want to record the originating `request_id` alongside `api_key_id`, and is `progress` (JSONB) wanted in v1 or deferred to a later migration? (§5.3)
5. **TTL for completed/failed job rows — accept the proposed 7-day default, or pick a different value?** This was not explicitly discussed during the design conversation; 7 days is offered as a defensible starting point. (§5.3)
6. **Tool protocol's optional `startup()` / `shutdown()` hooks (§6.1) — accept as optional members invoked by `hasattr` check, or require them on every tool as no-op defaults?** Optional is the more YAGNI-aligned choice; required would give static type-checkers a clean target. (§6.1, §10.1)
7. **Are the recommendations on URL layout and Tool-protocol shape approved as written, or are there modifications the designer wants before implementation?** (§4.1, §6.1)
8. **Is `>=0.0.20` of the `greekroom` PyPI package an acceptable dependency floor, given its alpha designation?** Alternatives are a git pin to a specific commit, or a slightly looser/tighter version constraint. (§9.1)
9. **Is the proposed `ToolExecutionException` (502, code `TOOL_EXECUTION_ERROR`) the correct shape, or does the designer prefer reusing the existing `ExternalServiceException`?** (§8.1)
10. **Are there any callers of the eventual endpoint that need to be looped in on the contract before it solidifies?** The status-envelope shape is the part with the highest cost of later change.

---

## 13. Appendix — Illustrative Code Sketches

> The sketches below exist to make the shapes in this document concrete enough to evaluate. They are **illustrative, not prescriptive.** The implementer is expected to make the final calls on naming, signatures, type-hint style, and import layout, consistent with the rest of the Fluent-AI codebase.

### 13.1 The `Tool` protocol

A minimal structural protocol. Every concrete tool exposes the same four members; the registry and the generic dispatch layer never need to import a tool by name.

```python
# src/app/services/tool_registry.py  (protocol portion)
from typing import Protocol, ClassVar
from pydantic import BaseModel


class Tool(Protocol):
    """Structural contract every Fluent-AI tool implements."""

    name: ClassVar[str]                       # e.g. "greek_room.repeated_words"
    request_schema: ClassVar[type[BaseModel]]
    response_schema: ClassVar[type[BaseModel]]

    async def execute(self, request: BaseModel) -> BaseModel:
        """Run the tool. Must return an instance of response_schema."""
        ...
```

### 13.2 Self-registration and auto-discovery

The registry is a dictionary; tools register themselves at import time. A package-level walker imports every submodule of `app.services.greek_room` so that no central manifest needs editing when a new tool is added.

```python
# src/app/services/tool_registry.py  (registry portion)
_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    """Idempotent on identical re-registration; rejects same-name collisions."""
    if tool.name in _REGISTRY and _REGISTRY[tool.name] is not tool:
        raise RuntimeError(f"Tool name collision: {tool.name!r}")
    _REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Tool:
    return _REGISTRY[name]


def all_tools() -> dict[str, Tool]:
    return dict(_REGISTRY)


def discover(package_name: str) -> None:
    """Import every submodule of the given package so registrations fire."""
    import importlib
    import pkgutil

    pkg = importlib.import_module(package_name)
    for mod in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{package_name}.{mod.name}")
```

The `lifespan` handler calls `tool_registry.discover("app.services.greek_room")` once at startup (and one such call per tool family); from that point on, `all_tools()` reflects everything that exists on disk in that namespace.

### 13.3 A concrete tool: `RepeatedWordsTool`

This is the entire surface of a tool. The JSON-RPC envelope that greek-room expects internally is constructed and unpacked here and **nowhere else**; the rest of Fluent-AI never sees it.

```python
# src/app/services/greek_room/repeated_words.py
import asyncio
import json
import uuid
from typing import ClassVar

from greekroom.owl import repeated_words as gr_rw

from app.errors.exceptions import ToolExecutionException
from app.schemas.greek_room import (
    RepeatedWordsRequest,
    RepeatedWordsResult,
    RepeatedWordsFinding,
)
from app.services import tool_registry


class RepeatedWordsService:
    name: ClassVar[str] = "greek_room.repeated_words"
    request_schema: ClassVar[type] = RepeatedWordsRequest
    response_schema: ClassVar[type] = RepeatedWordsResult

    def __init__(self) -> None:
        # One-time load at startup; cheap and idempotent.
        self._data_files = gr_rw.load_data_filename()

    async def execute(self, request: RepeatedWordsRequest) -> RepeatedWordsResult:
        message_id = f"{request.lang_code}-{uuid.uuid4().hex[:8]}"
        envelope = self._build_jsonrpc_envelope(request, message_id)
        try:
            mcp_d, _misc, _corpus = await asyncio.to_thread(
                gr_rw.check_mcp,
                json.dumps(envelope),
                self._data_files,
                gr_rw.new_corpus(message_id),
            )
        except Exception as exc:
            raise ToolExecutionException(
                tool=self.name,
                message="repeated-words check failed",
            ) from exc

        return self._flatten(mcp_d, request)

    # --- private helpers (envelope construction & flattening) -----------

    @staticmethod
    def _build_jsonrpc_envelope(req: RepeatedWordsRequest, message_id: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "BibleTranslationCheck",
            "params": [{
                "lang-code": req.lang_code,
                "lang-name": req.lang_name,
                "project-id": req.project_id,
                "project-name": req.project_name,
                "selectors": [{"tool": "GreekRoom", "checks": ["RepeatedWords"]}],
                "check-corpus": [
                    {"snt-id": v.snt_id, "text": v.text} for v in req.verses
                ],
            }],
        }

    @staticmethod
    def _flatten(mcp_d: dict, req: RepeatedWordsRequest) -> RepeatedWordsResult:
        # Greek-room's `check_mcp` returns an envelope of the shape:
        #     {
        #       "jsonrpc": "2.0",
        #       "id": "...",
        #       "result-timestamp": "...",
        #       "lang-code": "...",
        #       "result": [{
        #         "tool": "GreekRoom",
        #         "checks": [{
        #           "check": "RepeatedWords",
        #           "feedback": [
        #             {"snt-id": "GEN 1:1",
        #              "repeated-word": "in in",
        #              "surf": "In in",
        #              "start-position": 0,
        #              "legitimate": false,
        #              "severity": 0.5},
        #             ...
        #           ]
        #         }]
        #       }]
        #     }
        # The flattening drills exactly that path and pulls the feedback list out.
        feedback_raw: list[dict] = []
        for result_block in (mcp_d or {}).get("result", []) or []:
            for check_block in result_block.get("checks", []) or []:
                if check_block.get("check") == "RepeatedWords":
                    feedback_raw.extend(check_block.get("feedback", []) or [])

        findings = [
            RepeatedWordsFinding(
                snt_id=item["snt-id"],
                repeated_word=item.get("repeated-word", ""),
                surf=item.get("surf", ""),
                start_position=int(item.get("start-position", 0)),
                legitimate=bool(item.get("legitimate", False)),
                severity=float(item.get("severity", 0.5)),
            )
            for item in feedback_raw
        ]
        from app.schemas.greek_room import RepeatedWordsSummary

        return RepeatedWordsResult(
            lang_code=req.lang_code,
            findings=findings,
            summary=RepeatedWordsSummary(
                total_findings=len(findings),
                legitimate_count=sum(1 for f in findings if f.legitimate),
                verse_count=len(req.verses),
            ),
        )


tool_registry.register(RepeatedWordsService())
```

Two things worth noting:

- **`asyncio.to_thread`** keeps the FastAPI event loop free while greek-room's synchronous regex work runs.
- The **JSON-RPC envelope is private to this module**. Callers see only flat Pydantic types; greek-room's internal protocol never leaks past this file.

### 13.4 The route handler (Option A shape)

The route validates the request via Pydantic, looks up the tool in the registry, calls `execute`, and wraps the result in the status envelope. There is no tool-specific code in the routing layer.

```python
# src/app/api/v1/endpoints/greek_room.py
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status

from app.dependencies import require_api_key
from app.models.api_key import ApiKey
from app.schemas.greek_room import RepeatedWordsRequest, RepeatedWordsResult
from app.schemas.tool_job import ToolJobResponse
from app.services import tool_registry

router = APIRouter(prefix="/tools/greek-room", tags=["tools:greek-room"])


@router.post(
    "/repeated-words",
    response_model=ToolJobResponse[RepeatedWordsResult],
    status_code=status.HTTP_200_OK,
    summary="Run the greek-room repeated-words check",
)
async def check_repeated_words(
    request: RepeatedWordsRequest,
    api_key: ApiKey = Depends(require_api_key),
) -> ToolJobResponse[RepeatedWordsResult]:
    tool = tool_registry.get("greek_room.repeated_words")
    created_at = datetime.now(timezone.utc)
    result = await tool.execute(request)
    return ToolJobResponse[RepeatedWordsResult](
        job_id=str(uuid.uuid4()),
        tool=tool.name,
        status="completed",
        result=result,
        created_at=created_at,
        completed_at=datetime.now(timezone.utc),
    )
```

The endpoint is intentionally small and survives the Option A → Option B cutover by being rewritten to enqueue a `tool_jobs` row instead of calling `execute` inline; the URL, request schema, and response-envelope shape are unchanged in either direction.

Under Option B, the equivalent handler becomes roughly:

```python
async def submit_repeated_words(
    request: RepeatedWordsRequest,
    api_key: ApiKey = Depends(require_api_key),
    jobs: ToolJobService = Depends(get_tool_job_service),
) -> ToolJobResponse[RepeatedWordsResult]:
    job = await jobs.submit(
        tool_name="greek_room.repeated_words",
        request=request,
        api_key=api_key,
    )
    return ToolJobResponse[RepeatedWordsResult].from_job_row(job)
```

…and the worker process (W1/W2/W3) is what eventually calls `tool_registry.get(...).execute(request)`.

### 13.5 The schemas in one place

The request and result schemas (already shown in §4.4 and §4.6) and the status envelope (§4.5) are reproduced here as a single file for completeness. The generic `ToolJobResponse[ResultT]` lives in its own module so that every tool's endpoint can return a parameterized instance of it.

```python
# src/app/schemas/greek_room.py
from pydantic import BaseModel, Field


class VerseInput(BaseModel):
    snt_id: str = Field(..., description="Scripture reference, e.g. 'GEN 1:1'")
    text: str


class RepeatedWordsRequest(BaseModel):
    lang_code: str = Field(..., description="ISO 639-3 language code, e.g. 'eng'")
    lang_name: str
    project_id: str
    project_name: str
    verses: list[VerseInput]


class RepeatedWordsFinding(BaseModel):
    snt_id: str
    repeated_word: str
    surf: str
    start_position: int
    legitimate: bool
    severity: float


class RepeatedWordsSummary(BaseModel):
    total_findings: int
    legitimate_count: int
    verse_count: int


class RepeatedWordsResult(BaseModel):
    lang_code: str
    tool: str = "GreekRoom"
    check: str = "RepeatedWords"
    findings: list[RepeatedWordsFinding]
    summary: RepeatedWordsSummary
```

```python
# src/app/schemas/tool_job.py
from datetime import datetime
from typing import Generic, Literal, TypeVar
from pydantic import BaseModel


ResultT = TypeVar("ResultT", bound=BaseModel)


class ToolError(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ToolJobResponse(BaseModel, Generic[ResultT]):
    job_id: str
    tool: str
    status: Literal["queued", "running", "completed", "failed"]
    result: ResultT | None = None
    error: ToolError | None = None
    created_at: datetime
    completed_at: datetime | None = None
```

The envelope shape is the **single most important contract in this document**, because it is the contract every future Fluent-AI tool will share. Changes after launch are expensive; the four-state `status` field and the parameterized `result` slot are the parts most worth locking in early.

### 13.6 `ToolExecutionException`

```python
# src/app/errors/exceptions.py  (addition)
from app.errors.codes import ErrorCode


class ToolExecutionException(FluentAIException):
    """A tool implementation failed during execution.

    Distinct from generic 500s (unexpected platform errors) and from
    ExternalServiceException (HTTP-upstream failures); this signals that
    a tool's own execution did not complete successfully, for reasons
    internal to the tool but not the platform.
    """

    status_code = 502
    default_code = ErrorCode.TOOL_EXECUTION_ERROR
    default_message = "Tool execution failed."

    def __init__(
        self,
        *,
        tool: str,
        message: str | None = None,
        details: dict | None = None,
    ) -> None:
        merged_details = {"tool": tool, **(details or {})}
        super().__init__(
            message=message or self.default_message,
            details=merged_details,
        )
```

The constructor accepts an optional `details` dict so a caller can attach extra context (e.g. the underlying exception type, the offending field, an internal diagnostic) while the `tool` key is always populated. The cause chain is preserved at the call site with `raise ToolExecutionException(...) from exc`.

```python
# src/app/errors/codes.py  (addition to the existing ErrorCode collection)
TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
```

A single new code constant; a single new exception class; no other plumbing required — the existing handler hierarchy in `app/errors/handlers.py` already serialises any `FluentAIException` subclass into the project's `ErrorResponse` shape.

---

*End of document.*

