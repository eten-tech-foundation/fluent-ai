"""Gating for the tests in this package that touch real infrastructure.

Everything under `tests/tts/` runs against fakes except `test_real_smoke.py`,
which spends provider money and writes to the real R2 bucket. Rather than rely
on a reader noticing the marker, the skip is enforced here: a `real_infra` test
is **collected but skipped** unless `TTS_SMOKE_REAL=1` is in the environment.

Collected-and-skipped rather than deselected on purpose — a normal `pytest
tests/` reports the smoke as skipped, so the suite says out loud that a real
check exists and was not run, instead of hiding it.
"""

import os

import pytest


REAL_INFRA_ENV_VAR = "TTS_SMOKE_REAL"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip `real_infra` tests unless the opt-in env var is set to `1`."""
    if os.getenv(REAL_INFRA_ENV_VAR) == "1":
        return
    skip = pytest.mark.skip(
        reason=(
            f"real infrastructure test; set {REAL_INFRA_ENV_VAR}=1 to run it "
            "(bills Gemini and writes to the configured R2 bucket)"
        )
    )
    for item in items:
        if "real_infra" in item.keywords:
            item.add_marker(skip)
