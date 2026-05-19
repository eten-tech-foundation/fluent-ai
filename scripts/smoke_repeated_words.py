#!/usr/bin/env python3
"""Manual smoke test for ``POST /tools/greek-room/repeated-words``.

Hits the running fluent-ai service over real HTTP (not the in-process
TestClient that the pytest suite uses) with a small canned 3-verse corpus
that exercises:

* one verse with a suspicious duplicate (``"In in the beginning ..."``)
* one verse with a legitimate duplicate (``"Truly, truly, I say unto thee."``)
* one clean verse with no duplicates

It is deliberately a thin "does the deployed service respond correctly"
probe, not a substitute for the authoritative pytest suite
(``./fai.sh test tests/api/v1/test_greek_room.py``).

Usage::

    # default — http://localhost:8200, key from .env or DEV_API_KEY env var
    python scripts/smoke_repeated_words.py

    # override URL and key explicitly
    python scripts/smoke_repeated_words.py --url http://localhost:8200 \
                                           --key fai_dev_admin

    # print the raw response body (no assertions, no pretty-printing)
    python scripts/smoke_repeated_words.py --raw

Exit status:

* ``0`` — request succeeded and (unless ``--raw``) all sanity checks passed
* ``1`` — HTTP error, unexpected response shape, or failed sanity check
* ``2`` — bad CLI arguments

Requires only the Python standard library. Runs on Windows and Linux.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Request body — must stay in sync with tests/api/v1/test_greek_room.py
# so that "what passes in pytest" and "what this script sends" agree.
# ---------------------------------------------------------------------------
SAMPLE_REQUEST: dict[str, Any] = {
    "lang_code": "eng",
    "lang_name": "English",
    "project_id": "smoke-test",
    "project_name": "Smoke Test",
    "verses": [
        {
            "snt_id": "GEN 1:1",
            "text": "In in the beginning God created the heavens.",
        },
        {
            "snt_id": "JHN 3:3",
            "text": "Truly, truly, I say unto thee.",
        },
        {
            "snt_id": "PSA 23:1",
            "text": "The Lord is my shepherd.",
        },
    ],
}


def load_dev_api_key_from_dotenv() -> str | None:
    """Best-effort read of ``DEV_API_KEY`` from a sibling ``.env`` file.

    The script is intentionally tolerant: a missing or unreadable .env is
    not an error, it just means the caller must supply the key by other
    means (``--key`` or ``FLUENT_AI_KEY`` env var).
    """
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",  # fluent-ai/.env
        Path.cwd() / ".env",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == "DEV_API_KEY":
                    return value.strip().strip('"').strip("'") or None
        except OSError:
            continue
    return None


def resolve_api_key(cli_value: str | None) -> str:
    """CLI flag > ``FLUENT_AI_KEY`` env var > ``DEV_API_KEY`` in .env > fallback."""
    if cli_value:
        return cli_value
    env_value = os.environ.get("FLUENT_AI_KEY")
    if env_value:
        return env_value
    dotenv_value = load_dev_api_key_from_dotenv()
    if dotenv_value:
        return dotenv_value
    # Last-resort default — matches .env.example's seeded dev key.
    return "fai_dev_admin"


def resolve_url(cli_value: str | None) -> str:
    if cli_value:
        return cli_value.rstrip("/")
    env_value = os.environ.get("FLUENT_AI_URL")
    if env_value:
        return env_value.rstrip("/")
    return "http://localhost:8200"


def post_json(url: str, body: dict[str, Any], api_key: str, timeout: float) -> tuple[int, bytes, str]:
    """POST a JSON body and return ``(status_code, raw_body, content_type)``.

    HTTPError responses are converted to a normal ``(status, body, ct)``
    tuple so the caller can render them just like any other response.
    """
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-Key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "") if exc.headers else ""


def try_parse_json(raw: bytes) -> Any | None:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def run_sanity_checks(payload: Any) -> list[tuple[bool, str]]:
    """Light shape assertions. The authoritative suite lives in pytest."""
    checks: list[tuple[bool, str]] = []

    def record(label: str, passed: bool) -> None:
        checks.append((passed, label))

    if not isinstance(payload, dict):
        record("response is a JSON object", False)
        return checks
    record("response is a JSON object", True)

    record(
        'envelope.status == "completed"',
        payload.get("status") == "completed",
    )
    record(
        'envelope.tool == "greek_room.repeated_words"',
        payload.get("tool") == "greek_room.repeated_words",
    )

    result = payload.get("result")
    if not isinstance(result, dict):
        record("envelope.result is a JSON object", False)
        return checks
    record("envelope.result is a JSON object", True)

    findings = result.get("findings")
    if not isinstance(findings, list):
        record("result.findings is a list", False)
        return checks
    record("result.findings is a list", True)

    record(
        "result.findings has exactly 2 entries",
        len(findings) == 2,
    )
    legitimate = [f for f in findings if isinstance(f, dict) and f.get("legitimate") is True]
    suspicious = [f for f in findings if isinstance(f, dict) and f.get("legitimate") is False]
    record("exactly one legitimate finding", len(legitimate) == 1)
    record("exactly one suspicious finding", len(suspicious) == 1)

    summary = result.get("summary")
    if isinstance(summary, dict):
        record("summary.verse_count == 3", summary.get("verse_count") == 3)
    else:
        record("summary is a JSON object", False)

    return checks


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test for POST /tools/greek-room/repeated-words.",
    )
    parser.add_argument(
        "--url",
        help=(
            "Base URL of the fluent-ai service "
            "(default: $FLUENT_AI_URL or http://localhost:8200)."
        ),
    )
    parser.add_argument(
        "--key",
        help=(
            "API key to send in X-API-Key "
            "(default: $FLUENT_AI_KEY, then DEV_API_KEY from .env, then 'fai_dev_admin')."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the response body verbatim and skip sanity checks.",
    )
    args = parser.parse_args(argv)

    base_url = resolve_url(args.url)
    api_key = resolve_api_key(args.key)
    endpoint = f"{base_url}/tools/greek-room/repeated-words"

    redacted = api_key[:8] + "…(redacted)" if len(api_key) > 8 else "(redacted)"
    print(f"POST {endpoint}", file=sys.stderr)
    print(f"X-API-Key: {redacted}", file=sys.stderr)
    print("", file=sys.stderr)

    try:
        status, raw_body, _content_type = post_json(
            endpoint, SAMPLE_REQUEST, api_key, args.timeout
        )
    except urllib.error.URLError as exc:
        print(f"error: could not reach {endpoint}: {exc.reason}", file=sys.stderr)
        return 1
    except TimeoutError:
        print(f"error: request to {endpoint} timed out", file=sys.stderr)
        return 1

    print(f"HTTP {status}", file=sys.stderr)
    print("", file=sys.stderr)

    if args.raw:
        # Verbatim body to stdout; non-zero exit on non-200 so it composes
        # with shell pipelines.
        sys.stdout.buffer.write(raw_body)
        if not raw_body.endswith(b"\n"):
            sys.stdout.buffer.write(b"\n")
        return 0 if status == 200 else 1

    payload = try_parse_json(raw_body)
    if payload is None:
        print("error: response was not valid JSON; raw body follows:", file=sys.stderr)
        sys.stderr.buffer.write(raw_body)
        sys.stderr.buffer.write(b"\n")
        return 1

    # Pretty-print to stdout.
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    if status != 200:
        print(f"\nerror: expected HTTP 200, got {status}", file=sys.stderr)
        return 1

    print("", file=sys.stderr)
    print("--- response shape sanity checks ---", file=sys.stderr)
    results = run_sanity_checks(payload)
    failed = False
    for passed, label in results:
        marker = "ok  " if passed else "FAIL"
        print(f"  {marker} {label}", file=sys.stderr)
        if not passed:
            failed = True

    print("", file=sys.stderr)
    if failed:
        print("one or more sanity checks failed", file=sys.stderr)
        return 1
    print("smoke test passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
