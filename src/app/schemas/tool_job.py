# src/app/schemas/tool_job.py
"""
Generic response envelope shared by every Fluent-AI tool endpoint.

Every tool endpoint returns a ToolJobResponse[SomeResult] regardless of
whether the work is executed inline or queued for later. This keeps the
external contract uniform across synchronous and asynchronous execution
modes — callers that always inspect `status` before reading `result`
stay forward-compatible across both.

Current execution mode is synchronous (status is always "completed" on
success), but the envelope is structured so a future async job queue
can be layered in without breaking callers.

Note: this module uses the older TypeVar/Generic[T] syntax rather than
PEP 695 generic-class syntax because Pydantic v2's generic-model
machinery integrates more cleanly with the TypeVar form.
"""

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

ResultT = TypeVar("ResultT", bound=BaseModel)


JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class ToolError(BaseModel):
    """Structured error payload for failed tool runs.

    Populated on the envelope when `status == "failed"`. Mirrors the wire
    shape produced by the global FluentAIException handlers so that
    failed-job payloads and HTTP error bodies stay consistent.
    """

    code: str
    message: str
    details: dict | None = None


class ToolJobResponse(BaseModel, Generic[ResultT]):
    """Universal response envelope for tool endpoints.

    Fields:
        job_id:        Per-invocation identifier. Currently a UUID generated
                       at response time with no server-side persistence; if a
                       job queue is introduced later this becomes the row id.
        tool:          Fluent-AI tool identifier (e.g. "greek_room.repeated_words").
        status:        One of "queued", "running", "completed", "failed",
                       "cancelled". Synchronous endpoints currently return
                       "completed" on success and surface failures as HTTP
                       errors rather than failed-job envelopes.
        result:        Populated when status == "completed". Type-parameterized
                       to the specific tool's result schema.
        error:         Populated when status == "failed".
        created_at:    Submission timestamp (UTC).
        completed_at:  Terminal-state timestamp (UTC) for completed/failed/
                       cancelled, else None.
    """

    job_id: str
    tool: str
    status: JobStatus
    result: ResultT | None = None
    error: ToolError | None = None
    created_at: datetime
    completed_at: datetime | None = None
