# src/app/services/tts/artifacts.py
"""
The R2 artifact store (proposal §9.3): request sidecars, audio, receipts.

There is no database and no staging filesystem. An artifact exists in a
generation buffer, exists on R2, or does not exist — so the store is the only
record and no tracking state can ever disagree with the bytes.

Three prefixes live under `TTS_R2_PREFIX`:

    requests/{hash}.json    immutable synthesis recipe = capability + recipe
    audio/{hash}.{ogg,mp3}  immutable compressed artifact, publicly served
    receipts/{hash}.json    best-effort metadata, written last, never required

`requests/` is kept separate precisely so the optional WAF path-block described
in §7.3 stays a one-rule affair.

Why boto3 in a thread: R2 speaks S3, and botocore is synchronous. Calls are
issued through `asyncio.to_thread` so the event loop keeps serving other
readers during a round-trip. A botocore client is safe to share across threads
(unlike a boto3 *resource*), so one client per process is correct.
"""

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.errors.codes import ErrorCode
from app.errors.exceptions import ExternalServiceException, ServiceUnavailableException
from app.logging.utils import get_logger


if TYPE_CHECKING:  # pragma: no cover - typing only
    from mypy_boto3_s3.client import S3Client

    from app.config import Settings


logger = get_logger(__name__)


REQUESTS_PREFIX = "requests/"
AUDIO_PREFIX = "audio/"
RECEIPTS_PREFIX = "receipts/"

JSON_CONTENT_TYPE = "application/json"

_PRECONDITION_FAILED_CODES = frozenset({"PreconditionFailed", "412"})
"""How a conditional-PUT conflict arrives.

Verified against the real dev bucket on 2026-08-11: R2 does enforce
`If-None-Match: *`, answering `412 PreconditionFailed` when the key exists. The
numeric spelling is accepted too because botocore falls back to the status code
when a response carries no error code.
"""


@dataclass(frozen=True)
class ObjectHead:
    """What a HEAD tells us about a stored object."""

    key: str
    size_bytes: int
    etag: str | None
    content_type: str | None


def serialize_json_body(body: dict[str, Any]) -> bytes:
    """Serialize sidecar/receipt JSON deterministically.

    Sorted keys and fixed separators mean two replicas writing the same logical
    sidecar produce identical bytes. That is what lets a conditional-PUT
    conflict be treated as success without wondering whether the winning copy
    differs from ours.
    """
    return json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")


class TtsArtifactStore:
    """Thin, purpose-built wrapper over the S3 API of one R2 bucket.

    Deliberately not a general-purpose S3 helper: it exposes only the four
    operations the TTS design needs (conditional PUT, plain PUT, HEAD, GET) and
    it owns the key layout, so no caller has to know how a hash becomes a key.
    """

    def __init__(self, *, client: "S3Client", bucket: str, prefix: str = "") -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix

    # ------------------------------------------------------------------ #
    # Key layout
    # ------------------------------------------------------------------ #

    def request_key(self, artifact_hash: str) -> str:
        return f"{self._prefix}{REQUESTS_PREFIX}{artifact_hash}.json"

    def audio_key(self, artifact_hash: str, extension: str) -> str:
        return f"{self._prefix}{AUDIO_PREFIX}{artifact_hash}.{extension}"

    def receipt_key(self, artifact_hash: str) -> str:
        return f"{self._prefix}{RECEIPTS_PREFIX}{artifact_hash}.json"

    # ------------------------------------------------------------------ #
    # Operations
    # ------------------------------------------------------------------ #

    async def put_if_absent(self, key: str, body: bytes, *, content_type: str) -> bool:
        """Conditionally PUT an object; return True if this call wrote it.

        A conflict is **success, not an error** (§9.3, §10.1): first writer
        wins, the object is immutable, and every writer is trying to store the
        same artifact for the same hash. Returning False rather than raising is
        what makes repeated `generate` calls idempotent no-ops.
        """
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                IfNoneMatch="*",
            )
        except ClientError as exc:
            if _is_precondition_failed(exc):
                logger.debug(
                    "tts artifact already present; conditional PUT is a no-op",
                    key=key,
                )
                return False
            raise _storage_error("write", key, exc) from exc
        except BotoCoreError as exc:
            raise _storage_error("write", key, exc) from exc
        return True

    async def put(self, key: str, body: bytes, *, content_type: str) -> None:
        """Unconditional PUT, for objects whose last writer may win.

        Used only where overwriting is harmless and a conflict would be noise;
        sidecars and audio must use `put_if_absent` so immutability holds.
        """
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        except (ClientError, BotoCoreError) as exc:
            raise _storage_error("write", key, exc) from exc

    async def head(self, key: str) -> ObjectHead | None:
        """HEAD an object; None when it does not exist.

        Absence is an ordinary answer here — it is how the serving waterfall
        decides which rung applies (§7.2) — so it is not an exception.
        """
        try:
            response = await asyncio.to_thread(
                self._client.head_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if _is_missing(exc):
                return None
            raise _storage_error("head", key, exc) from exc
        except BotoCoreError as exc:
            raise _storage_error("head", key, exc) from exc

        return ObjectHead(
            key=key,
            size_bytes=int(response.get("ContentLength", 0)),
            etag=response.get("ETag"),
            content_type=response.get("ContentType"),
        )

    async def get_bytes(self, key: str) -> bytes | None:
        """GET an object's bytes; None when it does not exist."""
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
            return await asyncio.to_thread(response["Body"].read)
        except ClientError as exc:
            if _is_missing(exc):
                return None
            raise _storage_error("read", key, exc) from exc
        except BotoCoreError as exc:
            raise _storage_error("read", key, exc) from exc

    async def get_json(self, key: str) -> dict[str, Any] | None:
        """GET and parse a JSON object; None when it does not exist.

        A present-but-unparseable body is a storage error rather than a
        silent None: pretending the sidecar is absent would send the waterfall
        to its 404 rung and tell the client to re-authorize an artifact that is
        in fact already authorized.
        """
        raw = await self.get_bytes(key)
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExternalServiceException(
                message="Stored TTS artifact metadata is not valid JSON.",
                code=ErrorCode.TTS_STORAGE_ERROR,
                details={"key": key},
            ) from exc
        if not isinstance(parsed, dict):
            raise ExternalServiceException(
                message="Stored TTS artifact metadata is not a JSON object.",
                code=ErrorCode.TTS_STORAGE_ERROR,
                details={"key": key},
            )
        return parsed


# --------------------------------------------------------------------------- #
# Error helpers
# --------------------------------------------------------------------------- #


def _error_code(exc: ClientError) -> str:
    error = exc.response.get("Error", {})
    code = error.get("Code")
    if code:
        return str(code)
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return str(status) if status else ""


def _is_precondition_failed(exc: ClientError) -> bool:
    return _error_code(exc) in _PRECONDITION_FAILED_CODES


def _is_missing(exc: ClientError) -> bool:
    return _error_code(exc) in {"404", "NoSuchKey", "NotFound"}


def _storage_error(
    operation: str, key: str, exc: Exception
) -> ExternalServiceException:
    """Wrap a storage failure without leaking credentials or endpoint detail.

    The key is safe to include (it is already public knowledge to whoever holds
    the URL) and is the one thing an operator needs to correlate logs.
    """
    logger.error(
        "tts artifact store operation failed",
        operation=operation,
        key=key,
        error=str(exc),
    )
    return ExternalServiceException(
        message="The TTS artifact store is unavailable.",
        code=ErrorCode.TTS_STORAGE_ERROR,
        details={"operation": operation, "key": key},
    )


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #


def build_artifact_store(settings: "Settings") -> TtsArtifactStore:
    """Build the store from settings, or fail cleanly if TTS is unconfigured.

    Called per request (cheaply, via a cached dependency) rather than at import
    time: a deployment with no audio bucket must still boot and serve
    everything else, so missing configuration surfaces here as a 503 on TTS
    routes only.
    """
    if not settings.is_tts_storage_configured:
        raise ServiceUnavailableException(
            message=(
                "TTS artifact storage is not configured on this deployment "
                "(R2 credentials, bucket, or hash secret missing)."
            ),
            code=ErrorCode.TTS_STORAGE_NOT_CONFIGURED,
        )

    endpoint_url = settings.r2_endpoint_url
    # Belt-and-braces: is_tts_storage_configured already requires the account
    # id, so this is unreachable — but a None endpoint would otherwise be
    # requested as the literal string "https://None...".
    if endpoint_url is None:  # pragma: no cover - guarded by the check above
        raise ServiceUnavailableException(
            message="TTS artifact storage has no derivable R2 endpoint.",
            code=ErrorCode.TTS_STORAGE_NOT_CONFIGURED,
        )

    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        # Both are required for R2, and both were confirmed against the real
        # bucket on 2026-08-11: R2 has no regions (so 'auto') and rejects
        # anything but SigV4.
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    assert settings.r2_tts_bucket is not None  # narrowed by the check above
    return TtsArtifactStore(
        client=client,
        bucket=settings.r2_tts_bucket,
        prefix=settings.tts_r2_prefix,
    )
