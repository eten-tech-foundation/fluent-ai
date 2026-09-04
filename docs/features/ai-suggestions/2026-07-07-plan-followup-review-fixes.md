# Suggestions Follow-up Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the still-valid findings from a second review pass over the AI-suggestions feature (fluent-ai), while skipping fabricated/unenforced/out-of-scope findings with documented reasons.

**Architecture:** Small, targeted edits across the suggestions schema/service/endpoint, the `Job` model, and one new Alembic migration for a DB-level status CHECK constraint. No architectural changes.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, SQLAlchemy 2.0 async ORM, Alembic, pytest + pytest-asyncio.

## Global Constraints

- Test command: `uv run pytest src/tests -v`. Lint: `uv run ruff check src`. Migration check: `uv run alembic heads` / `uv run alembic upgrade head` against a real Postgres instance if available; otherwise review the generated SQL by eye.
- Current alembic head is `20260629_1355_create_jobs` — any new migration's `down_revision` must be exactly that string.
- `Job.updated_at` / `created_at` are deliberately **naive** `DateTime` columns matching Postgres's actual `TIMESTAMP WITHOUT TIME ZONE` type, and `reclaim_stale_jobs` deliberately compares naive-to-naive. **Do not change this in this plan** — see "Findings explicitly skipped" below.
- Do not change the wire format of `POST /suggestions` (still a JSON array of camelCase objects) except to add validation that rejects genuinely-invalid input (inverted verse ranges, batches over the cap, malformed book codes) — valid existing payloads must continue to work unchanged.
- One pre-existing, unrelated test failure predates this work and is out of scope: `src/tests/test_google_gemini.py::test_generate_content_returns_text`.

## Findings explicitly skipped (do not implement these)

1. **"Rename `trigger_suggestions` to a `create_`-prefixed name."** No such convention exists in this codebase. Sibling endpoint handlers use domain verbs (`translate_verses`, `check_repeated_words`, `list_keys`, `patch_key`, `revoke_key`) — `create_` is used only where a single resource is literally created (`create_key`). `trigger_suggestions` already fits the codebase's actual naming pattern. Renaming it would be a cosmetic, unrequired change with no basis.
2. **"Make `Job.created_at`/`updated_at` timezone-aware; make `reclaim_stale_jobs` compare tz-aware UTC."** This was deliberately investigated and reverted in a prior session: a tz-aware cutoff compared against Postgres's naive `TIMESTAMP WITHOUT TIME ZONE` column raises `TypeError: can't subtract offset-naive and offset-aware datetimes` via asyncpg — on every single production poll cycle, stalling the whole worker. Applying this finding safely requires an actual DDL migration (`ALTER COLUMN ... TYPE TIMESTAMPTZ`) changing the real Postgres column type, not just a model annotation change — a materially larger and riskier change than the rest of this plan. Recommend as a separate, explicitly-scoped follow-up if timezone-awareness is genuinely needed, not bundled here.
3. **"Split `process_job` into `fetch_context`/`_build_translate_request`/`_save_results` helpers to satisfy lint thresholds."** Verified: this repo's `pyproject.toml` has no `[tool.ruff.lint]` complexity rule selected (only Ruff's default `E4/E7/E9/F`), and `ruff check` on this file currently passes clean — there is no enforced lint threshold being violated. The whole function runs inside one `async with httpx.AsyncClient() as client:` block; splitting it into standalone helpers would require passing `client` through each one or restructuring the client's lifecycle, which risks the extensive, already-hardened retry/rollback/non-retryable-error logic in this function. Not worth the risk for a non-enforced style preference; skip.
4. **"Convert f-string logger calls to structured kwargs per Ruff G004."** Verified: Ruff's `G` (flake8-logging-format) rule category, including G004, is not selected in this repo's Ruff config — `ruff check` does not flag this file. The codebase itself is inconsistent (`services/translation_service.py` uses structured kwargs; `core/ai_clients/google_gemini.py` uses f-strings, same as this file) — there is no single enforced "app style" to align to. Rewriting every log line in `suggestion_processor.py` for a non-enforced, inconsistently-applied style is a large diff with no functional benefit; skip.

---

## File Structure

| File | Change |
|---|---|
| `src/app/core/constants.py` | Add `MAX_SUGGESTION_BATCH_SIZE` |
| `src/app/api/v1/endpoints/suggestions.py` | Reject batches over the size cap |
| `src/app/schemas/suggestions.py` | Add `verse_start <= verse_end` validator; constrain `book_code` to a safe charset |
| `src/app/db/migrations/versions/20260629_1355_create_jobs_table.py` | Modernize `Union`/`Sequence` typing to match the sibling migration's style |
| `src/app/models/job.py` | Add `Literal` status type hint + DB-level `CheckConstraint` |
| `src/app/db/migrations/versions/<new>.py` | New migration adding the status CHECK constraint |
| `src/app/worker/suggestion_processor.py` | Mark job `"failed"` (not `"completed"`) when zero items survive the per-item verse-matching loop |
| `src/tests/test_suggestions_service.py` | Tests for batch-size cap, verse-range validation, book_code validation |
| `src/tests/worker/test_suggestion_processor.py` | Test for the all-items-dropped path |

---

## Task 1: Cap the suggestion-trigger batch size (review finding #2)

**Files:**
- Modify: `src/app/core/constants.py`
- Modify: `src/app/api/v1/endpoints/suggestions.py`
- Test: `src/tests/test_suggestions_service.py` (append) — actually this test needs the FastAPI `TestClient` since the cap is enforced at the endpoint layer, not inside `enqueue_suggestion_jobs`. Create `src/tests/api/v1/test_suggestions.py` instead (matching the existing `src/tests/api/v1/` layout used for other endpoint tests).

**Interfaces:**
- Produces: `MAX_SUGGESTION_BATCH_SIZE = 100` in `core/constants.py`. Requests exceeding this raise a 400 `ValidationException` before any DB work happens.

- [ ] **Step 1: Add the constant**

In `src/app/core/constants.py`, add below `STALE_PROCESSING_TIMEOUT_MINUTES`:
```python

# Maximum number of SuggestionTriggerRequest items accepted in a single
# POST /suggestions call. Prevents an unbounded batch from enqueueing an
# arbitrarily large number of jobs in one request.
MAX_SUGGESTION_BATCH_SIZE = 100
```

- [ ] **Step 2: Write the failing test**

Read `src/tests/api/v1/test_api_keys.py` first to match its exact `TestClient`/fixture/auth-header pattern (it already exercises an authenticated endpoint via `require_api_key`), then create `src/tests/api/v1/test_suggestions.py` following that same pattern:
```python
"""
tests/api/v1/test_suggestions.py — Tests for the POST /suggestions endpoint.
"""

import pytest

from app.core.constants import MAX_SUGGESTION_BATCH_SIZE


def _request(verse_start: int = 1) -> dict:
    return {
        "projectUnitId": 1,
        "bibleId": 1,
        "bookCode": "MAT",
        "chapterNumber": 1,
        "verseStart": verse_start,
        "verseEnd": verse_start,
    }


def test_trigger_suggestions_rejects_batch_over_max_size(client, api_key_header):
    oversized = [_request(i) for i in range(MAX_SUGGESTION_BATCH_SIZE + 1)]
    response = client.post("/suggestions", json=oversized, headers=api_key_header)
    assert response.status_code == 400


def test_trigger_suggestions_accepts_batch_at_max_size(client, api_key_header, monkeypatch):
    from unittest.mock import AsyncMock

    import app.api.v1.endpoints.suggestions as suggestions_endpoint

    monkeypatch.setattr(
        suggestions_endpoint,
        "enqueue_suggestion_jobs",
        AsyncMock(return_value={"message": "Queued 100 jobs"}),
    )
    at_max = [_request(i) for i in range(MAX_SUGGESTION_BATCH_SIZE)]
    response = client.post("/suggestions", json=at_max, headers=api_key_header)
    assert response.status_code != 400
```
Adjust the `client`/`api_key_header` fixture names to whatever `src/tests/api/v1/test_api_keys.py` and `src/tests/api/v1/conftest.py` (if one exists) actually define — read them first, don't guess the fixture names.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest src/tests/api/v1/test_suggestions.py -v`
Expected: `test_trigger_suggestions_rejects_batch_over_max_size` FAILS (no cap currently enforced, so it doesn't return 400).

- [ ] **Step 4: Enforce the cap in the endpoint**

In `src/app/api/v1/endpoints/suggestions.py`, replace:
```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_api_key
from app.schemas.suggestions import SuggestionTriggerRequest, SuggestionTriggerResponse
from app.services.suggestions import enqueue_suggestion_jobs

router = APIRouter()


@router.post(
    "",
    response_model=SuggestionTriggerResponse,
    summary="Trigger AI suggestion jobs",
    dependencies=[Depends(require_api_key)],
)
async def trigger_suggestions(
    requests: list[SuggestionTriggerRequest],
    db: AsyncSession = Depends(get_db),
) -> SuggestionTriggerResponse:
    """
    Enqueue AI translation suggestion jobs in the generic jobs table.
    """
    return await enqueue_suggestion_jobs(db, requests)
```
with:
```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MAX_SUGGESTION_BATCH_SIZE
from app.dependencies import get_db, require_api_key
from app.errors.exceptions import ValidationException
from app.schemas.suggestions import SuggestionTriggerRequest, SuggestionTriggerResponse
from app.services.suggestions import enqueue_suggestion_jobs

router = APIRouter()


@router.post(
    "",
    response_model=SuggestionTriggerResponse,
    summary="Trigger AI suggestion jobs",
    dependencies=[Depends(require_api_key)],
)
async def trigger_suggestions(
    requests: list[SuggestionTriggerRequest],
    db: AsyncSession = Depends(get_db),
) -> SuggestionTriggerResponse:
    """
    Enqueue AI translation suggestion jobs in the generic jobs table.
    """
    if len(requests) > MAX_SUGGESTION_BATCH_SIZE:
        raise ValidationException(
            message=(
                f"Batch of {len(requests)} requests exceeds the maximum of "
                f"{MAX_SUGGESTION_BATCH_SIZE} per call."
            ),
            details={"count": len(requests), "max": MAX_SUGGESTION_BATCH_SIZE},
        )
    return await enqueue_suggestion_jobs(db, requests)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest src/tests/api/v1/test_suggestions.py -v`
Expected: `2 passed`

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `uv run pytest src/tests -v`
Expected: previously-passing count + 2, same one pre-existing unrelated failure.

- [ ] **Step 7: Commit**

```bash
git add src/app/core/constants.py src/app/api/v1/endpoints/suggestions.py src/tests/api/v1/test_suggestions.py
git commit -m "fix: cap POST /suggestions batch size to prevent unbounded job creation"
```

---

## Task 2: Modernize typing imports in the jobs-table migration (review finding #3)

**Files:**
- Modify: `src/app/db/migrations/versions/20260629_1355_create_jobs_table.py`

**Interfaces:** None — annotation-only change, no behavior/DDL difference.

- [ ] **Step 1: Confirm the sibling migration's pattern**

Read `src/app/db/migrations/versions/20260512_0900_create_ai_api_keys.py` lines 1-25 to confirm the exact import (`from collections.abc import Sequence`) and annotation style (`str | Sequence[str] | None`) used there — match it exactly.

- [ ] **Step 2: Update the jobs-table migration**

In `src/app/db/migrations/versions/20260629_1355_create_jobs_table.py`, replace:
```python
from typing import Sequence, Union
```
with:
```python
from collections.abc import Sequence
```
Replace each of:
```python
down_revision: Union[str, Sequence[str], None] = "20260512_0900"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
```
with:
```python
down_revision: str | Sequence[str] | None = "20260512_0900"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
```

- [ ] **Step 3: Verify the migration still loads correctly**

Run: `uv run alembic heads`
Expected: still reports `20260629_1355_create_jobs (head)` — confirms the file still imports and parses correctly with no chain breakage.

Run: `uv run ruff check src/app/db/migrations/versions/20260629_1355_create_jobs_table.py`
Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add src/app/db/migrations/versions/20260629_1355_create_jobs_table.py
git commit -m "chore: modernize typing imports in jobs-table migration to match sibling migration"
```

---

## Task 3: Add a DB-level CHECK constraint on `Job.status` (review finding #4)

**Files:**
- Modify: `src/app/models/job.py`
- Create: `src/app/db/migrations/versions/<new_revision>.py`
- Test: `src/tests/test_suggestions_service.py` or a new `src/tests/test_job_model.py` (see Step 4)

**Interfaces:**
- Produces: `Job.status` keeps its Python type as `str` at the ORM/DB layer (`String(20)`, unchanged runtime column type) but gains a `Literal["queued", "processing", "completed", "failed"]` type-hint for static analysis, plus a real Postgres `CHECK` constraint rejecting any other value at the DB layer.

- [ ] **Step 1: Add the type hint and CHECK constraint to the model**

Read `src/app/models/job.py` in full first (confirm current line numbers before editing — they will have shifted since prior sessions touched this file).

Add `Literal` to the `typing` import (or `from typing import Literal` as a new import line if none exists), and `CheckConstraint` to the `sqlalchemy` import line.

Change:
```python
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'queued'")
    )
```
to:
```python
    status: Mapped[Literal["queued", "processing", "completed", "failed"]] = mapped_column(
        String(20), nullable=False, server_default=text("'queued'")
    )
```

In `__table_args__`, add a `CheckConstraint` alongside the existing `Index`/`UniqueConstraint`:
```python
    __table_args__ = (
        Index("idx_jobs_status_created", "status", "created_at"),
        UniqueConstraint("dedup_key", name="uq_jobs_dedup_key"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="ck_jobs_status_valid",
        ),
        {"schema": "ai"},
    )
```
(Match this to the file's actual current `__table_args__` layout — insert the `CheckConstraint` before the trailing `{"schema": "ai"}` dict, which must remain last.)

- [ ] **Step 2: Generate the new migration**

Run: `uv run alembic revision -m "add_jobs_status_check_constraint"`

This creates a new file under `src/app/db/migrations/versions/`. Rename it to follow the repo's existing `YYYYMMDD_HHMM_<slug>.py` convention (check the generated filename's timestamp and adjust to match the sibling files' naming if the autogenerated name differs), and edit its contents to:
```python
"""add_jobs_status_check_constraint

Revision ID: <new_id>
Revises: 20260629_1355_create_jobs
Create Date: <keep as generated>

"""

from collections.abc import Sequence

from alembic import op

revision: str = "<new_id>"
down_revision: str | Sequence[str] | None = "20260629_1355_create_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_jobs_status_valid",
        "jobs",
        "status IN ('queued', 'processing', 'completed', 'failed')",
        schema="ai",
    )


def downgrade() -> None:
    op.drop_constraint("ck_jobs_status_valid", "jobs", schema="ai", type_="check")
```
Replace `<new_id>` with whatever revision id Alembic actually generated (do not hand-invent one — use the tool's output so it matches Alembic's internal bookkeeping).

- [ ] **Step 3: Verify the migration chain and (if a database is reachable) apply it**

Run: `uv run alembic heads`
Expected: reports your new revision as the head, chained after `20260629_1355_create_jobs`.

If a local/dev Postgres is reachable via `DATABASE_URL`/`MIGRATIONS_DATABASE_URL`: run `uv run alembic upgrade head` and confirm it applies cleanly with no errors. If no database is reachable in this environment, skip actual application and note this in the report — do not fabricate a successful run.

- [ ] **Step 4: Write a model-level test confirming the type hint doesn't break existing behavior**

The CHECK constraint itself can only be verified against real Postgres (SQLite's `CheckConstraint` support is inconsistent and the existing SQLite test fixtures explicitly clone/patch the table schema, which may or may not carry the constraint through — don't assume it does). Instead, add a lightweight test confirming the model still round-trips normal status values correctly under the existing SQLite fixture, to catch any accidental breakage from the `Literal` type-hint change:

Append to `src/tests/worker/test_suggestion_processor.py` (reuses the existing `db_session`/`make_job` fixtures):
```python
@pytest.mark.asyncio
async def test_job_status_accepts_all_four_valid_values(db_session, make_job):
    for status in ("queued", "processing", "completed", "failed"):
        job = await make_job(status=status, dedup_key=f"ai_suggestion:test:{status}")
        assert job.status == status
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_job_status_accepts_all_four_valid_values -v`
Expected: PASS

- [ ] **Step 6: Run the full suite and lint to check for regressions**

Run: `uv run pytest src/tests -v` — expect no new failures beyond the one pre-existing unrelated one.
Run: `uv run mypy src/app/models/job.py` — confirm the `Literal` change doesn't introduce a new mypy error (SQLAlchemy's `Mapped[Literal[...]]` with an explicit `mapped_column(String(20))` override should type-check fine, but verify).

- [ ] **Step 7: Commit**

```bash
git add src/app/models/job.py src/app/db/migrations/versions/ src/tests/worker/test_suggestion_processor.py
git commit -m "feat: add DB-level CHECK constraint on Job.status and a Literal type hint"
```

---

## Task 4: Reject inverted verse ranges (review finding #6)

**Files:**
- Modify: `src/app/schemas/suggestions.py`
- Test: `src/tests/test_suggestions_service.py` (append)

**Interfaces:**
- Produces: `SuggestionTriggerRequest.model_validate(...)` raises a Pydantic `ValidationError` (→ FastAPI 422) when `verse_start > verse_end`.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/test_suggestions_service.py`:
```python
def test_suggestion_trigger_request_rejects_inverted_verse_range():
    from pydantic import ValidationError

    from app.schemas.suggestions import SuggestionTriggerRequest

    with pytest.raises(ValidationError):
        SuggestionTriggerRequest.model_validate(
            {
                "projectUnitId": 1,
                "bibleId": 1,
                "bookCode": "MAT",
                "chapterNumber": 1,
                "verseStart": 5,
                "verseEnd": 1,
            }
        )


def test_suggestion_trigger_request_accepts_equal_verse_start_and_end():
    from app.schemas.suggestions import SuggestionTriggerRequest

    req = SuggestionTriggerRequest.model_validate(
        {
            "projectUnitId": 1,
            "bibleId": 1,
            "bookCode": "MAT",
            "chapterNumber": 1,
            "verseStart": 5,
            "verseEnd": 5,
        }
    )
    assert req.verse_start == req.verse_end == 5
```
Add `import pytest` to the top of the file if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/test_suggestions_service.py::test_suggestion_trigger_request_rejects_inverted_verse_range -v`
Expected: FAIL (no validation currently exists, so no `ValidationError` is raised).

- [ ] **Step 3: Add the validator**

In `src/app/schemas/suggestions.py`, add `model_validator` to the `pydantic` import and add the validator method to the class:
```python
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SuggestionTriggerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_unit_id: int = Field(alias="projectUnitId")
    bible_id: int = Field(alias="bibleId")
    book_code: str = Field(alias="bookCode")
    chapter_number: int = Field(alias="chapterNumber")
    verse_start: int = Field(alias="verseStart")
    verse_end: int = Field(alias="verseEnd")

    @model_validator(mode="after")
    def _verse_range_is_ordered(self) -> "SuggestionTriggerRequest":
        if self.verse_start > self.verse_end:
            raise ValueError(
                f"verse_start ({self.verse_start}) must be <= verse_end ({self.verse_end})"
            )
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/tests/test_suggestions_service.py -v`
Expected: all tests in the file pass, including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add src/app/schemas/suggestions.py src/tests/test_suggestions_service.py
git commit -m "fix: reject inverted verse ranges in SuggestionTriggerRequest"
```

---

## Task 5: Constrain `book_code` to a safe charset to prevent dedup_key collisions (review finding #7)

**Files:**
- Modify: `src/app/schemas/suggestions.py`
- Test: `src/tests/test_suggestions_service.py` (append)

**Interfaces:**
- Produces: `SuggestionTriggerRequest` rejects `book_code` values containing the `:` character (or any non-alphanumeric character), closing the dedup_key collision gap since the key format uses `:` as its field separator.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/test_suggestions_service.py`:
```python
def test_suggestion_trigger_request_rejects_book_code_with_separator_char():
    from pydantic import ValidationError

    from app.schemas.suggestions import SuggestionTriggerRequest

    with pytest.raises(ValidationError):
        SuggestionTriggerRequest.model_validate(
            {
                "projectUnitId": 1,
                "bibleId": 1,
                "bookCode": "MAT:1",
                "chapterNumber": 1,
                "verseStart": 1,
                "verseEnd": 1,
            }
        )


def test_suggestion_trigger_request_accepts_normal_book_code():
    from app.schemas.suggestions import SuggestionTriggerRequest

    req = SuggestionTriggerRequest.model_validate(
        {
            "projectUnitId": 1,
            "bibleId": 1,
            "bookCode": "MAT",
            "chapterNumber": 1,
            "verseStart": 1,
            "verseEnd": 1,
        }
    )
    assert req.book_code == "MAT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/test_suggestions_service.py::test_suggestion_trigger_request_rejects_book_code_with_separator_char -v`
Expected: FAIL (no charset constraint exists yet).

- [ ] **Step 3: Add the constraint**

In `src/app/schemas/suggestions.py`, change the `book_code` field from:
```python
    book_code: str = Field(alias="bookCode")
```
to:
```python
    book_code: str = Field(alias="bookCode", pattern=r"^[A-Za-z0-9]+$")
```
This is a proportionate fix: it doesn't hardcode the exact set of valid Bible book codes (which would need to track USFM/Paratext book-code standards and could go stale), but it does guarantee `book_code` can never contain `:` — the separator character `dedup_key` is built from — closing the collision described in the finding.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/tests/test_suggestions_service.py -v`
Expected: all tests pass.

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run pytest src/tests -v`
Expected: no new failures beyond the one pre-existing unrelated one.

- [ ] **Step 6: Commit**

```bash
git add src/app/schemas/suggestions.py src/tests/test_suggestions_service.py
git commit -m "fix: constrain book_code charset to prevent dedup_key collisions"
```

---

## Task 6: Mark job "failed" instead of "completed" when zero items survive filtering (review finding #10)

**Files:**
- Modify: `src/app/worker/suggestion_processor.py`
- Test: `src/tests/worker/test_suggestion_processor.py` (append)

**Interfaces:** No signature changes — hardens the existing end-of-`process_job` status assignment.

- [ ] **Step 1: Write the failing test**

Append to `src/tests/worker/test_suggestion_processor.py` (reuse the existing `httpx.AsyncClient.post` monkeypatch pattern from `test_process_job_skips_malformed_verse_id_instead_of_failing_job`):
```python
@pytest.mark.asyncio
async def test_process_job_fails_when_all_items_are_dropped(db_session, make_job):
    """If every item in the LLM response is malformed or out of range, the
    job should be marked 'failed' (nothing was actually saved), not silently
    'completed' — mirroring the existing 'no source verses' failure path."""
    job = await make_job(retry_count=0)

    translation_service = AsyncMock()
    translation_service.settings.api_base_url = "http://fluent-api:9999"
    translation_service.settings.api_service_key = "test-key"
    translation_service.settings.google_ai_model = "gemini-test"
    translation_service.translate_verses.return_value = SimpleNamespace(
        translations=[
            SimpleNamespace(verse_id="not-a-valid-id", target_text="bad"),
            SimpleNamespace(verse_id="MAT_1_999", target_text="out of range"),
        ]
    )

    class _FakeContextResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "targetLanguageName": "Spanish",
                "contextVerses": [],
                "sourceVerses": [{"id": 42, "verse_number": 1, "text": "In the beginning"}],
            }

    async def _fake_post(self, url, *args, **kwargs):
        return _FakeContextResponse()

    orig_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _fake_post
    try:
        await process_job(db_session, job, translation_service)
    finally:
        httpx.AsyncClient.post = orig_post

    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_message is not None
```
(`AsyncMock`, `SimpleNamespace`, `httpx`, and `process_job` should already be imported at the top of this file from prior tasks — add any missing ones to the existing consolidated import block, don't create a new mid-file import.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_process_job_fails_when_all_items_are_dropped -v`
Expected: FAIL — `job.status == "completed"` currently, not `"failed"`.

- [ ] **Step 3: Fix the completion logic**

In `src/app/worker/suggestion_processor.py`, replace:
```python
            if items:
                save_resp = await client.post(
                    f"{api_base_url}/ai-suggestions/internal/results",
                    headers=headers,
                    json={"items": items},
                    timeout=30.0,
                )
                try:
                    save_resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if 400 <= exc.response.status_code < 500:
                        raise NonRetryableJobError(
                            f"fluent-api rejected results push with "
                            f"{exc.response.status_code}: {exc}"
                        ) from exc
                    raise

        job.status = "completed"
        await db.commit()
        logger.info(f"Job {job.id} completed successfully.")
```
with:
```python
            if not items:
                job.status = "failed"
                job.error_message = (
                    f"No valid translations to save for {book_code} "
                    f"{chapter_number}:{verse_start}-{verse_end} — all "
                    f"{len(result.translations)} LLM-returned item(s) were "
                    f"malformed or out of the requested range."
                )
                await db.commit()
                return

            save_resp = await client.post(
                f"{api_base_url}/ai-suggestions/internal/results",
                headers=headers,
                json={"items": items},
                timeout=30.0,
            )
            try:
                save_resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if 400 <= exc.response.status_code < 500:
                    raise NonRetryableJobError(
                        f"fluent-api rejected results push with "
                        f"{exc.response.status_code}: {exc}"
                    ) from exc
                raise

        job.status = "completed"
        await db.commit()
        logger.info(f"Job {job.id} completed successfully.")
```
(This inverts the guard from `if items:` to an early-return `if not items:`, mirroring the existing `if not source_verses:` early-failure pattern earlier in the same function, and dedents the results-push logic by removing the now-redundant `if items:` wrapper since the function already returned for the empty case.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest src/tests/worker/test_suggestion_processor.py::test_process_job_fails_when_all_items_are_dropped -v`
Expected: PASS

- [ ] **Step 5: Run the full worker test file to check for regressions**

Run: `uv run pytest src/tests/worker/ -v`
Expected: all previously-passing tests still pass, plus the new one — pay particular attention to `test_process_job_skips_malformed_verse_id_instead_of_failing_job` and `test_process_job_skips_non_string_verse_id_instead_of_crashing`, which both leave exactly one valid item and must still end up `"completed"` (they exercise the non-empty `items` path, which must be unaffected by this change).

- [ ] **Step 6: Run the full suite and lint**

Run: `uv run pytest src/tests -v` — expect no new failures beyond the one pre-existing unrelated one.
Run: `uv run ruff check src/app/worker/suggestion_processor.py` — expect clean.

- [ ] **Step 7: Commit**

```bash
git add src/app/worker/suggestion_processor.py src/tests/worker/test_suggestion_processor.py
git commit -m "fix: mark job failed instead of completed when zero valid items survive filtering"
```

---

## Final verification

- [ ] Run the full suite one more time: `uv run pytest src/tests -v` — expect all green except the one pre-existing unrelated `test_google_gemini.py` failure.
- [ ] Run lint: `uv run ruff check src` — expect clean.
- [ ] Run `uv run alembic heads` — expect the new CHECK-constraint migration as the sole head, chained correctly after `20260629_1355_create_jobs`.
- [ ] Re-read the 10 original findings and confirm: #2, #3, #4, #6, #7, #10 are each addressed by a task above; #1, #5, #8, #9 are documented as explicitly skipped with reasons in the Global Constraints section.
