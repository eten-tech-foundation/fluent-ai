# src/app/services/greek_room/repeated_words.py
"""
Service layer for the Greek-Room *Repeated Words* check.

This module is the only place that knows about greek-room's JSON-RPC
envelope shape. Route handlers and other callers see only the flat
Pydantic types defined in app.schemas.greek_room.

The class exposes the registry-ready surface (`name`, `request_schema`,
`response_schema`, `async execute`) so that a future tool registry can
adopt it without modification.
"""

import asyncio
import json
import uuid
from typing import ClassVar

from greekroom.owl import repeated_words as gr_rw

from app.errors.exceptions import ToolExecutionException
from app.logging.utils import get_logger
from app.schemas.greek_room import (
    RepeatedWordsFinding,
    RepeatedWordsRequest,
    RepeatedWordsResult,
    RepeatedWordsSummary,
)

logger = get_logger(__name__)


# Upstream provider and check identifiers — used both for selecting the
# right feedback block out of the JSON-RPC envelope and for populating
# the result body's `provider` / `check` fields.
_PROVIDER = "GreekRoom"
_CHECK = "RepeatedWords"


class RepeatedWordsService:
    """Wraps greek-room's repeated-words check behind a Fluent-AI service.

    Data files (the bundled `legitimate_duplicates.jsonl`) are loaded once
    in `__init__`; the per-request `execute()` call assembles a JSON-RPC
    envelope, offloads the CPU-bound check to a worker thread via
    `asyncio.to_thread`, and flattens the response into the
    `RepeatedWordsResult` shape.
    """

    # Registry-ready surface: name, request_schema, response_schema, execute.
    # Not currently used by a registry; kept stable so a future registry
    # PR can discover and dispatch this service without modifying it.
    name: ClassVar[str] = "greek_room.repeated_words"
    request_schema: ClassVar[type[RepeatedWordsRequest]] = RepeatedWordsRequest
    response_schema: ClassVar[type[RepeatedWordsResult]] = RepeatedWordsResult

    def __init__(self) -> None:
        # One-time load at construction. The data-file dict is shared
        # across every request this instance handles.
        self._data_filename_dict = gr_rw.load_data_filename()
        logger.info(
            "RepeatedWordsService initialised",
            data_files=self._data_filename_dict.get("repeated-words", []),
        )

    async def execute(self, request: RepeatedWordsRequest) -> RepeatedWordsResult:
        """Run the repeated-words check against the supplied corpus."""
        message_id = self._make_message_id(request.lang_code)
        envelope = self._build_jsonrpc_envelope(request, message_id)

        try:
            mcp_d, _misc_data, _check_corpus_list = await asyncio.to_thread(
                gr_rw.check_mcp,
                json.dumps(envelope),
                self._data_filename_dict,
                gr_rw.new_corpus(message_id),
            )
        except Exception as exc:
            logger.exception(
                "Greek-room repeated-words check failed",
                tool=self.name,
                lang_code=request.lang_code,
                verse_count=len(request.verses),
            )
            raise ToolExecutionException(
                tool=self.name,
                message="Repeated-words check failed.",
                details={"reason": str(exc)},
            ) from exc

        feedback = gr_rw.get_feedback(mcp_d, _PROVIDER, _CHECK) or []
        return self._build_result(feedback, request)

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_message_id(lang_code: str) -> str:
        """Per-request identifier used by greek-room for its own correlation."""
        return f"{lang_code}-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _build_jsonrpc_envelope(
        request: RepeatedWordsRequest, message_id: str
    ) -> dict:
        """Translate the flat Fluent-AI request into greek-room's JSON-RPC shape."""
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "BibleTranslationCheck",
            "params": [
                {
                    "lang-code": request.lang_code,
                    "lang-name": request.lang_name,
                    "project-id": request.project_id,
                    "project-name": request.project_name,
                    "selectors": [{"tool": _PROVIDER, "checks": [_CHECK]}],
                    "check-corpus": [
                        {"snt-id": v.snt_id, "text": v.text} for v in request.verses
                    ],
                }
            ],
        }

    @staticmethod
    def _build_result(
        feedback: list[dict], request: RepeatedWordsRequest
    ) -> RepeatedWordsResult:
        """Convert greek-room's hyphenated feedback items into our snake_case findings."""
        findings = [
            RepeatedWordsFinding(
                snt_id=item.get("snt-id", ""),
                repeated_word=item.get("repeated-word", ""),
                surf=item.get("surf", ""),
                start_position=int(item.get("start-position", 0)),
                legitimate=bool(item.get("legitimate", False)),
                severity=float(item.get("severity", 0.5)),
            )
            for item in feedback
        ]
        return RepeatedWordsResult(
            lang_code=request.lang_code,
            findings=findings,
            summary=RepeatedWordsSummary(
                total_findings=len(findings),
                legitimate_count=sum(1 for f in findings if f.legitimate),
                verse_count=len(request.verses),
            ),
        )
