# Greek-Room Integration — Decisions Addendum

**Companion to:** [`greek-room-integration-suggestion.md`](greek-room-integration-suggestion.md)

**Purpose:** Capture the concrete decisions made on top of the architecture pitch as the implementation progresses. This document is a living record — it grows as further questions are resolved. The original pitch document is left unchanged so the "as-proposed" state is preserved.

**Status:** Active. Updated as implementation proceeds.

**Governing principle (from the user):** *Minimal implementation that accomplishes the goal, so that if we have to pivot we have less to tear up and do differently. Each piece of code (including tests) must justify its ongoing maintenance cost; don't add things "as religion."*

---

## Decision Log

### D1 — Job execution model: **Option A (Lightweight-now)**
*Resolves §12 question #1; defaults §12 questions #2, #3, #4, #5 to "not applicable."*

Synchronous execution via `asyncio.to_thread`. No `tool_jobs` table, no polling endpoints, no worker, no Alembic migration. The response envelope (D3) keeps the queue-shaped contract so future clients written against an Option-B server are forward-compatible with today's server.

**Implication for files:** None of the Option-B-only files in §7.2 are created (no `endpoints/jobs.py`, no `models/tool_job.py`, no `crud/tool_jobs.py`, no `workers/`, no migration).

---

### D2 — Greek-room dependency: **Install and adapt**
*Resolves §12 question #8.*

Add `greekroom>=0.0.20` to `pyproject.toml` as a normal PyPI dependency. Run `uv sync`. If Python 3.14 wheel-availability problems surface (especially for `regex` / `unicodeblock` / `uroman`), address them at that point — do not preemptively add `build-essential` to the Dockerfile or pin to a git commit.

---

### D3 — Response envelope: **Full `ToolJobResponse[ResultT]` shape, no `/jobs/` endpoint**
*Refines §4.5, §5.2.*

The route returns the complete envelope (`job_id`, `tool`, `status`, `result`, `error`, `created_at`, `completed_at`) with `status="completed"` always. **Rationale (user):** future clients that already understand the full envelope (and would normally fetch from `/jobs/{id}` when `status != "completed"`) remain compatible with today's server. The reverse direction — today's clients against a future Option-B server — would require client-side migration to handle non-completed statuses.

`job_id` is a freshly generated UUID per request; it is **not persisted** server-side under Option A. The `/jobs/{job_id}` polling endpoint is **not implemented** (not even as a stub returning 404). It does not exist in this deployment.

---

### D4 — Tool registry: **Skip, but stay registry-ready**
*Defers §6 in its entirety; honors the spirit of summary commitment #2 without building the runtime machinery.*

No `app/services/tool_registry.py`. No `tool_registry.register(...)` call. No `pkgutil`-based auto-discovery in `lifespan`. The route handler instantiates and calls `RepeatedWordsService` directly via a `Depends(...)` provider.

**Constraint inherited from the user:** *"Don't write the code in a way that would make it hard to implement in the future."* Therefore `RepeatedWordsService` is written with the registry-ready surface:

- `name: ClassVar[str] = "greek_room.repeated_words"`
- `request_schema: ClassVar[type[BaseModel]] = RepeatedWordsRequest`
- `response_schema: ClassVar[type[BaseModel]] = RepeatedWordsResult`
- `async def execute(self, request: RepeatedWordsRequest) -> RepeatedWordsResult`

When a registry is added in a future PR, the only change is the route's dependency provider (resolve by name instead of constructing directly); the service class itself needs no modification.

---

### D5 — Router mounting: **Existing project convention**
*Resolves §12 question #7 (URL layout portion).*

`endpoints/greek_room.py` declares a bare `router = APIRouter()`. The prefix `/tools/greek-room` and `tags=["tools:greek-room"]` are applied in `app/api/v1/router.py` at the `include_router(...)` call — mirroring how `api_keys` is wired.

**Resulting URL today:** `POST /tools/greek-room/repeated-words`
**Resulting URL after eventual global `/api/v1` prefix in `main.py`:** `POST /api/v1/tools/greek-room/repeated-words` — moves automatically when that single line in `main.py` changes.

---

### D6 — `ToolExecutionException`: **Add as designed**
*Resolves §12 question #9.*

A new subclass of `FluentAIException` (status 502, code `TOOL_EXECUTION_ERROR`) and a new `ErrorCode.TOOL_EXECUTION_ERROR` constant. **Rationale:** distinguishes "tool's own execution failed" from "remote HTTP service was unreachable" (existing `ExternalServiceException`). The distinction will be reused by future tools (Gemini-backed, OpenAI-backed) that have *both* failure modes — HTTP upstream failures vs. tool-logic failures.

Implementation matches the §13.6 sketch: constructor takes `tool: str` as a required keyword and merges it into `details`.

---

### D7 — Service initialization: **Lifespan-loaded, `app.state`, `Depends(...)` provider**
*Adopts §10.1 as written.*

`RepeatedWordsService()` is instantiated once inside the FastAPI `lifespan` context manager and stashed on `app.state.repeated_words_service`. A dependency function `get_repeated_words_service(request: Request)` returns it. The route handler depends on that function.

**Benefits:** fail-fast at startup if the greek-room data file is missing; fast first request (data file loaded once); clean `app.dependency_overrides[get_repeated_words_service] = ...` swap for tests.

**Cost:** ~5 lines in `main.py`, ~3 lines for the dependency provider, one attribute on `app.state`. Acceptable.

---

### D8 — Test coverage: **Three tests, each with practical value**
*Refines §7.3 to match the user's "every test must earn its keep" principle.*

| # | Test | What it catches that nothing else catches |
|---|------|-------------------------------------------|
| 1 | **Happy-path** — 3-verse corpus (one clean, one legitimate duplicate, one suspicious duplicate) → real greek-room library → assert finding count and at least one `legitimate=True` and one `legitimate=False` | Proves the whole chain wires up: route, service, JSON-RPC envelope translation, flatten logic, response envelope, real greek-room library. The "did this thing actually work?" test, runnable headless. |
| 2 | **Tool failure → 502** — service raises an unexpected exception inside `execute`; assert response is 502 with `code == "TOOL_EXECUTION_ERROR"` | Verifies `ToolExecutionException` is raised and serialized correctly. Only test that catches a regression in the new exception class wiring. |
| 3 | **Missing API key → 401** — POST with no `X-API-Key` header | Catches the easy mistake of forgetting `Depends(require_api_key)` on the route. Cheap, high signal. |

Tests skipped (explicit non-decisions): no service-layer unit tests, no validation-error tests, no Pydantic-rejection tests, no registry tests (no registry exists), no `/jobs/` tests (no endpoint exists).

**Test corpus ambiguity:** if a test fails due to greek-room version-specific behavior on what counts as a "legitimate duplicate," that's a bridge to cross at that point — the test is fixed or relaxed then, not preemptively.

---

### D9 — Authentication: **`require_api_key` only**
*Resolves §4.3 as written.*

Any active, non-expired API key may call `POST /tools/greek-room/repeated-words`. No admin requirement. No new permission string like `tools:greek-room`. Per §3.6, abuse is not a vector for the first caller (same team owns both sides). Future permission-gating can be added without changing the contract for unprivileged tools.

---

### D10 — Greek-room API verification: **Use `get_feedback()` helper, sketch is mostly accurate**
*Refines §13.3.*

The greek-room source in [`greek-room/greekroom/greekroom/owl/repeated_words.py`](greek-room/greekroom/greekroom/owl/repeated_words.py:1) was inspected directly before writing the service. Confirmed:

| Function | Signature | Notes |
|----------|-----------|-------|
| `load_data_filename(explicit_data_filenames=None, verbose=False) -> dict` | Returns a `defaultdict(list)` with key `"repeated-words"` → list of data file paths. | Called once in `RepeatedWordsService.__init__` (per D7). |
| `new_corpus(corpus_id: str \| None = None) -> Corpus` | Returns a `general_util.Corpus` instance. | Passed to `check_mcp` per request. |
| `check_mcp(mcp_request: str, data_filename_dict: dict, corpus: Corpus, verbose=False) -> Tuple[dict, dict, List[dict]]` | First arg is a **JSON string** (not a dict). Returns `(return_object, misc_data_dict, check_corpus_list)`. | We invoke this via `asyncio.to_thread`. |
| `get_feedback(output_d: dict, tool: str, check: str) -> List[dict] \| None` | Drills the envelope and returns the `feedback` list directly. | **We use this helper** instead of writing our own drill code; less code on our side, and greek-room owns the envelope-shape concern. |

The flattening logic in the service therefore reduces to: call `get_feedback(mcp_d, "GreekRoom", "RepeatedWords")`, iterate the list, and rename hyphenated keys to snake_case for our `RepeatedWordsFinding` Pydantic model.

**Observed but not acted on:** `check_for_repeated_words` (line 153) loads the legitimate-duplicates file with `lang_code_restriction=None`, meaning all languages are considered. This is a property of greek-room's implementation, not our integration, and does not affect correctness for our caller's perspective.

---

### D11 — Dependency installation: **`uv add`, not direct edit**
*Refines D2.*

The greek-room dependency is added via `uv add 'greekroom>=0.0.20'` rather than hand-editing `pyproject.toml`. This atomically updates `pyproject.toml`, `uv.lock`, and the project's installed environment, avoiding lockfile drift.

If the install needs to happen inside the container (because the container's volume-mounted `pyproject.toml`/`uv.lock` are what `fai.sh test` uses), it is run on the host and the container picks up the new lock on its next `uv sync` — which the `fai.sh test` path runs implicitly via `uv run`.

---

### D12 — Test execution model: **In-container `TestClient`, no real HTTP**
*Documents the existing project pattern as it applies to our PR.*

The three tests from D8 run via `./fai.sh test`, which executes `uv run pytest tests/ -v` **inside** the `fluent-ai-ai` container (see [`fai.sh:458-460`](fluent-ai/fai.sh:458)). They use FastAPI's `TestClient` (per [`tests/conftest.py`](fluent-ai/tests/conftest.py:1)), which constructs the app in-process and dispatches ASGI calls directly — no real HTTP socket is opened. Auth is overridden via `app.dependency_overrides[require_api_key]`, matching the established pattern in [`tests/api/v1/test_api_keys.py`](fluent-ai/tests/api/v1/test_api_keys.py:1).

**External HTTP smoke testing** (a Python script on the host hitting `http://localhost:8200/...`) remains available informally because the container exposes port 8200, but no formal smoke-test harness is added in this PR.

---

## Open Items (Pending)

The following §12 questions are not yet decided. Each will be addressed if/when relevant to upcoming implementation work; many became moot under Option A (D1).

- §12 #2 — Worker tier W1 vs. W2 — **moot under Option A.**
- §12 #3 — Job ownership policy — **moot under Option A.**
- §12 #4 — `tool_jobs` schema — **moot under Option A.**
- §12 #5 — TTL on job rows — **moot under Option A.**
- §12 #6 — Tool protocol's optional `startup()`/`shutdown()` hooks — **moot, no protocol built (D4).**
- §12 #10 — Any callers to loop in on the contract before it solidifies — **not yet addressed.**

---

## Implementation File List (consolidating D1–D9)

**New files:**

```
src/app/
├── api/v1/endpoints/
│   └── greek_room.py                       # route handler (D5: bare APIRouter)
├── schemas/
│   ├── greek_room.py                       # RepeatedWordsRequest/Result + sub-models
│   └── tool_job.py                         # ToolJobResponse[ResultT] envelope (D3)
└── services/
    └── greek_room/
        ├── __init__.py                     # package marker
        └── repeated_words.py               # RepeatedWordsService (D4: registry-ready)

tests/api/v1/
└── test_greek_room.py                      # three tests (D8)
```

**Modified files:**

```
src/app/
├── api/v1/router.py                        # include greek_room router with prefix (D5)
├── dependencies.py                         # add get_repeated_words_service (D7)
├── errors/
│   ├── codes.py                            # add TOOL_EXECUTION_ERROR (D6)
│   └── exceptions.py                       # add ToolExecutionException (D6)
└── main.py                                 # lifespan instantiates RepeatedWordsService (D7)

pyproject.toml                              # add greekroom>=0.0.20 (D2)
```

**No new files for the registry** (D4), **no migration** (D1), **no `/jobs/` endpoint** (D3), **no `workers/` package** (D1).

---

*This addendum is updated as further decisions are made during implementation.*
