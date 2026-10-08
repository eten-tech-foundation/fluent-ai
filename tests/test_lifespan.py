"""
tests/test_lifespan.py — what the application does on the way down (§8.3).

The cancellation itself is asserted against the heap and the service
(`tests/tts/test_generation.py`, `tests/tts/test_waterfall.py`); what can only
be seen here is the wiring — that shutdown reaches the process's TTS service at
all, and that it does not *build* one on its way out.
"""

from fastapi.testclient import TestClient

import app.dependencies as dependencies
from app.main import app


class RecordingTtsService:
    """Stand-in for the process singleton: it only has to be shut down."""

    def __init__(self) -> None:
        self.shutdowns = 0

    async def shutdown(self) -> None:
        self.shutdowns += 1


def test_shutdown_cancels_the_process_tts_generations(monkeypatch):
    service = RecordingTtsService()
    monkeypatch.setattr(dependencies, "_tts_service", service)

    with TestClient(app):
        assert service.shutdowns == 0  # still up

    assert service.shutdowns == 1


def test_shutdown_never_builds_a_tts_service_that_was_never_used(monkeypatch):
    """A process that never synthesized has nothing to cancel, and building a
    service here would construct an R2 client for a process that is going away
    — or, with no TTS configuration at all, raise a 503 out of the lifespan and
    turn a clean shutdown into a crash."""
    monkeypatch.setattr(dependencies, "_tts_service", None)

    def fail_if_built(_settings):
        raise AssertionError("shutdown must not build a TTS service")

    monkeypatch.setattr(dependencies, "build_artifact_store", fail_if_built)

    with TestClient(app):
        pass

    assert dependencies.peek_tts_service() is None
