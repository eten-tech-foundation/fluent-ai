import os
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as pkg_version
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_env_file() -> str:
    """Get the environment-specific .env file path."""
    env = os.getenv("ENVIRONMENT", "development")
    if env == "production":
        return ".env.prod"
    # Try .env.dev first, fall back to .env
    if os.path.exists(".env.dev"):
        return ".env.dev"
    return ".env"


def _get_app_version() -> str:
    """Read version from installed package metadata, with a safe fallback."""
    try:
        return pkg_version("fluent-ai")
    except PackageNotFoundError:
        return "0.0.0-dev"


# --------------------------------------------------------------------------- #
# Source-TTS sizing
#
# Full evidence, the knob table, and how to size for a given container:
#   docs/features/source-tts/source-tts-capacity.md
#
# The short version. These are one dial, not three: the text limit fixes the
# clip ceiling (below), the ceiling divides the RAM budget into admission slots,
# and the inequality `text limit x bytes-per-char <= ceiling` must hold or an
# oversized text is billed and killed mid-stream instead of refused for free.
# `TtsService` warns at boot if an override breaks it.
# --------------------------------------------------------------------------- #

PCM_BYTES_PER_CHARACTER = 4_000
"""PCM bytes one character of text becomes, measured on a real Gemini clip.

54 characters produced 4.56 s of audio (114 deltas x 40 ms) and 24 kHz mono
16-bit PCM is 48,000 B/s, so ~12 characters per second. **One English clip** —
see the capacity doc, since scripts differ and this is the shakiest input here.
"""

CORPUS_LONGEST_VERSE_CHARS = 6_504
"""The longest single verse measured across the eBible corpus (2026-08-16).

1,005 translations, 11,227,230 verses. Not an estimate and not an artifact:
1KI 12:24 carries the Septuagint's long addition as one verse in LXX-based
English Bibles. Recorded because it is what `MAX_TEXT_CHARS` would have to be
for zero refusals; the capacity document records the survey method and results.
"""

MAX_TEXT_CHARS = 4_000
"""Longest text this service will speak (operator decision, 2026-08-16).

A point chosen on the coverage curve, not a safety multiple: it refuses 12 of
11,227,230 real verses (~1 in 936,000), all Septuagint mega-additions in a few
English study Bibles, and costs 16 admission slots at a 256 MiB budget. The
capacity doc has the whole curve and the RAM arithmetic for other points.
"""

MAX_CLIP_BYTES = MAX_TEXT_CHARS * PCM_BYTES_PER_CHARACTER  # 16 MB, ~333 s
"""Derived from `MAX_TEXT_CHARS` on purpose — see the inequality above."""


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=(".env", _get_env_file()),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="Fluent AI API")
    app_version: str = Field(default_factory=_get_app_version)
    # Commit the running image was built from; set by the deploy workflow.
    app_commit_sha: str = Field(default="unknown")
    debug: bool = Field(default=False)
    environment: str = Field(default="development")

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8200)

    # Database — ai_user connects as: read public, write ai
    # Use postgresql+asyncpg:// scheme for async SQLAlchemy
    # Example: postgresql+asyncpg://ai_user:pa$$word@db:5432/fluent
    # Database
    database_url: str = Field(
        description="Full asyncpg connection URL. Set in .env — never hardcode here."
    )

    # Connection pool settings
    db_pool_size: int = Field(default=5)  # number of persistent connections
    db_max_overflow: int = Field(default=10)  # extra connections above pool_size
    db_pool_timeout: int = Field(default=30)  # seconds to wait for a connection
    db_pool_recycle: int = Field(default=1800)  # recycle connections after 30 min

    # Security
    secret_key: str = Field(default="dev-secret-key-not-for-production")

    # API Keys
    api_key_default_expiry_days: int | None = Field(
        default=None,
        description=(
            "Default expiry in days applied when creating a new API key "
            "and no explicit expires_at is provided. None = never expires."
        ),
    )
    admin_api_key_hash: str | None = Field(
        default=None,
        description=(
            "SHA-256 hash of the seed admin API key. "
            "Set in .env — never put the raw key here."
        ),
    )

    # Error handling
    # Set show_stack_traces=True in .env to include tracebacks in dev.
    # Never enable in production — enforced by _enforce_production_safety below.
    show_stack_traces: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    _INSECURE_SECRET_KEY_DEFAULT = "dev-secret-key-not-for-production"
    _INSECURE_API_SERVICE_KEY_DEFAULT = "dev-inbound-key-replace-me"

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """Force show_stack_traces off in production, and refuse to boot
        with known placeholder secrets in production."""
        if self.environment == "production" and self.show_stack_traces:
            self.show_stack_traces = False

        if self.environment == "production":
            if self.secret_key == self._INSECURE_SECRET_KEY_DEFAULT:
                raise ValueError(
                    "secret_key is still set to its insecure development "
                    "default — set a real SECRET_KEY in production."
                )
            if self.api_service_key == self._INSECURE_API_SERVICE_KEY_DEFAULT:
                raise ValueError(
                    "api_service_key is still set to its insecure development "
                    "default — set a real API_SERVICE_KEY in production."
                )

        return self

    log_output: str = Field(
        default="stdout",
        description="Log destination: 'stdout', 'file', or 'both'.",
    )
    log_file_path: str = Field(
        default="/app/logs/app.log",
        description="Path for file log output. Used when log_output is 'file' or 'both'.",
    )
    log_rotation: bool = Field(
        default=True,
        description="Enable RotatingFileHandler. No effect when log_output is 'stdout'.",
    )
    log_rotation_max_bytes: int = Field(
        default=10_485_760,
        description="Max log file size in bytes before rotation (default 10 MB).",
    )
    log_rotation_backup_count: int = Field(
        default=5,
        description="Number of rotated backup files to retain.",
    )
    log_sampling_rate: float = Field(
        default=1.0,
        description=(
            "Fraction of INFO-level request logs to emit (0.0–1.0). "
            "1.0 = log everything. Reduce for high-throughput endpoints."
        ),
    )

    # AI Suggestion Worker
    enable_suggestion_worker: bool = Field(
        default=True,
        description="Enable the background AI suggestion worker loop.",
    )

    # External AI Services
    openai_api_key: str | None = Field(default=None)
    anthropic_api_key: str | None = Field(default=None)
    google_ai_api_key: str | None = Field(default=None)
    google_ai_model: str = Field(default="gemini-2.5-flash-lite")

    # Internal API Integration
    api_base_url: str = Field(
        description="Base URL of the fluent-api service. Set in .env — never hardcode here."
    )
    api_service_key: str = Field(
        description="Key used to authenticate outgoing requests to fluent-api. Set in .env — never hardcode here."
    )

    # ----------------------------------------------------------------- #
    # Source TTS — R2 artifact storage and synthesis recipe (§9.1, §9.3)
    #
    # ALL OF THIS IS OPTIONAL ON PURPOSE. Every credential below defaults
    # to None so a deployment with no TTS configuration still BOOTS; TTS
    # requests then fail cleanly at request time. Never raise at import
    # time from missing TTS config — an unrelated deployment must not lose
    # the whole service because it has no audio bucket.
    #
    # Credential var names are shared with fluent-api's R2 integration for
    # org consistency (cf. fluent-api/src/env.ts).
    # ----------------------------------------------------------------- #
    r2_account_id: str | None = Field(default=None)
    r2_access_key_id: str | None = Field(default=None)
    r2_secret_access_key: str | None = Field(default=None)
    r2_jurisdiction: str = Field(
        default="eu",
        description=(
            "Data-at-rest jurisdiction, pinned via the endpoint host. 'eu' keeps "
            "bytes in the EU (GDPR) and is the team's default — their issued "
            "endpoint carries '.eu.'. Use 'default' for an unpinned bucket."
        ),
    )
    r2_tts_bucket: str | None = Field(
        default=None, description="Bucket holding TTS sidecars, audio and receipts."
    )
    tts_r2_prefix: str = Field(
        default="",
        description=(
            "Key prefix inside the bucket, e.g. 'tts/'. The three artifact "
            "prefixes (requests/, audio/, receipts/) live under it."
        ),
    )
    tts_public_audio_base_url: str | None = Field(
        default=None,
        description=(
            "Public base URL of the R2 custom domain used as the 302 target for "
            "compressed audio (§7.3), e.g. 'https://dev.tts.fluent.bible'. When "
            "unset, audio redirects must fail cleanly — never emit a "
            "'None'-prefixed URL. qa/prod hostnames are not issued yet, so "
            "'unset' is a legitimate state for those deployments."
        ),
    )
    tts_hash_secret: str | None = Field(
        default=None,
        description=(
            "HMAC key for artifact identity (§9.1). Scripture text is public, so "
            "a bare content hash would be computable by anyone; this secret is "
            "what makes knowing a hash a capability on the public R2 domain. "
            "Set in .env — never hardcode here."
        ),
    )

    tts_model: str = Field(
        default="gemini-3.1-flash-tts-preview",
        description="Configurable because preview model names change (§8.4).",
    )
    tts_voice: str = Field(
        default="Kore", description="One deployment-wide voice in v1 (§8.4)."
    )
    tts_default_format: Literal["ogg-opus", "mp3"] = Field(
        default="ogg-opus",
        description=(
            "Format an omitted request `format` resolves to BEFORE hashing and "
            "sidecar creation (§7.1/CB2), so 'unspecified' never exists "
            "internally. Changing it shifts which artifact omitting clients get."
        ),
    )
    tts_max_text_length: int = Field(
        default=MAX_TEXT_CHARS,
        description=(
            "Longest text this service will speak, in characters. Refusal here "
            "precedes any provider call, so an oversized text costs nothing; "
            "raise it only together with TTS_MAX_CLIP_BYTES (docs/features/"
            "source-tts/source-tts-capacity.md has the curve and RAM arithmetic). "
            "This service is the SOLE authority on the limit (T27): fluent-api "
            "is a passive proxy that validates shape only and holds no copy of "
            "this number, so there is no second value to drift."
        ),
    )

    # ----------------------------------------------------------------- #
    # Source TTS — the generation heap's RAM budget (§9.2, T21/T25)
    #
    # These four numbers are one system, not four knobs: the admission gate
    # holds ⌊budget / per-clip ceiling⌋ slots, each slot is a WORST-CASE byte
    # reservation, and a request that cannot get one waits briefly and is then
    # refused with 503 + Retry-After. Change the budget or the ceiling and the
    # slot count moves with it.
    # ----------------------------------------------------------------- #
    tts_max_buffered_bytes: int = Field(
        default=256 * 1024 * 1024,
        description=(
            "RAM ceiling for in-flight generation buffers (§9.2). Slots = this "
            "divided by TTS_MAX_CLIP_BYTES, so RAISING THIS IS THE CHEAP WAY TO "
            "BUY CONCURRENCY — it costs no verse coverage, where lowering the "
            "ceiling does. Container memory wants ~1.5x headroom over it "
            "(ffmpeg subprocess, interpreter, fragmentation). Sizing table: "
            "docs/features/source-tts/source-tts-capacity.md."
        ),
    )
    tts_max_clip_bytes: int = Field(
        default=MAX_CLIP_BYTES,
        description=(
            "Per-clip byte ceiling: one admission slot's worst-case "
            "reservation, and the per-append tripwire that kills a generation "
            "growing past it. Derived from TTS_MAX_TEXT_LENGTH — lowering it "
            "alone reopens the billed-mid-stream gap the boot check warns "
            "about. Sizing table: "
            "docs/features/source-tts/source-tts-capacity.md."
        ),
    )
    tts_admission_wait_seconds: float = Field(
        default=3.0,
        description=(
            "How long a NEW generation waits for a slot before being refused "
            "(§9.2). A short queue absorbs bursts; a long one would just hold "
            "clients on a connection that is going to fail anyway."
        ),
    )
    tts_retry_after_seconds: int = Field(
        default=5,
        description=(
            "`Retry-After` value on an admission refusal. Slots are held for "
            "seconds each (synthesis runs ~1.3x realtime on a verse), so this "
            "is a realistic wait rather than a token value."
        ),
    )
    tts_generation_timeout_seconds: float = Field(
        default=900.0,
        description=(
            "Stall timeout on one detached generation task — NOT a limit on "
            "clip length (TTS_MAX_CLIP_BYTES is that). Without it, a provider "
            "that connects and then never sends another delta pins an "
            "admission slot forever: the task is neither failing nor "
            "finishing, so nothing releases the reservation, and the RAM "
            "budget's 'slots are held for seconds each' argument silently "
            "stops being true. Set above the provider's 655 s output cap "
            "(synthesis runs ~1.3x realtime), so it can only ever fire on a "
            "stall and never guillotine a legitimate clip. Added to the "
            "proposal's Sec 8.4 table 2026-08-16."
        ),
    )
    tts_reader_max_seconds: float = Field(
        default=900.0,
        description=(
            "Reader max-lifetime (§7.2.1): bounds how long one slow client can "
            "pin a finished buffer and its admission slot. Deliberately above "
            "the provider's own 655 s output ceiling, so a listener consuming a "
            "maximum-length clip at realtime is never cut off."
        ),
    )
    tts_ffmpeg_concurrency: int = Field(
        default=1,
        ge=1,
        description=(
            "Concurrent compression tails (§10.1). Recommended, not "
            "load-bearing: a verse-sized encode runs in well under a second "
            "(measured ~100x realtime), so serializing them costs almost "
            "nothing and keeps worst-case CPU and RSS flat — which matters "
            "because the encode runs alongside the generation buffers the RAM "
            "budget is already accounting for. Raise it only if compression is "
            "ever observed to be the bottleneck, which would mean clips are "
            "finishing faster than one core can encode them."
        ),
    )
    tts_ffmpeg_binary: str | None = Field(
        default=None,
        description=(
            "Path to the ffmpeg executable. Unset (the default) resolves the "
            "static binary shipped by the `imageio-ffmpeg` wheel, so the "
            "encoder needs nothing from the container image (§10.2); a value "
            "here overrides that. It exists because the bundled build is GPL "
            "(`--enable-gpl`) and ~77 MB — if either turns out to be "
            "unacceptable, a deployment can point at its own build without a "
            "code change while the packaging choice is settled."
        ),
    )

    @field_validator("tts_r2_prefix")
    @classmethod
    def _normalize_tts_r2_prefix(cls, value: str) -> str:
        """Normalize the prefix to '' or 'something/' so key joins stay trivial.

        Accepts 'tts', 'tts/', '/tts' and yields 'tts/'. Without this every
        caller has to guess whether to add a slash, and a doubled or missing
        separator silently creates a second, parallel artifact namespace.
        """
        trimmed = value.strip().strip("/")
        return f"{trimmed}/" if trimmed else ""

    @property
    def r2_endpoint_url(self) -> str | None:
        """Derive the R2 S3 endpoint; there is deliberately no env var for it.

        Mirrors fluent-api/src/lib/blob-storage.ts:52-59 exactly:
            eu      → https://{account}.eu.r2.cloudflarestorage.com
            default → https://{account}.r2.cloudflarestorage.com

        Returns None when the account id is unset, so callers surface a clean
        configuration error rather than requesting 'https://None...'.
        """
        if not self.r2_account_id:
            return None
        jurisdiction = self.r2_jurisdiction.strip().lower()
        segment = (
            f"{jurisdiction}." if jurisdiction and jurisdiction != "default" else ""
        )
        return f"https://{self.r2_account_id}.{segment}r2.cloudflarestorage.com"

    @property
    def is_tts_storage_configured(self) -> bool:
        """True when R2 artifact storage can actually be reached.

        The hash secret is included because an artifact name computed with a
        missing/blank secret is not a valid identity — it would be a bare hash
        of public text, which §9.1 exists to prevent.
        """
        return bool(
            self.r2_account_id
            and self.r2_access_key_id
            and self.r2_secret_access_key
            and self.r2_tts_bucket
            and self.tts_hash_secret
        )

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"

    @property
    def async_database_url(self) -> str:
        """
        Ensure the database URL uses the asyncpg driver.

        Handles the case where DATABASE_URL is set with a plain
        postgres:// or postgresql:// scheme (e.g. from .env).
        """
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()  # type: ignore[call-arg]
