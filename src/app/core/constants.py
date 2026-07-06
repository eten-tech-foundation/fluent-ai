"""
constants.py — Centralized configuration constants for the AI suggestion system.

All tunable values for the suggestion queue and background worker are
defined here. Import from this module instead of hardcoding values in
business logic. Context retrieval (translation memory selection) happens
server-side in fluent-api, not in this service.
"""

# ---------------------------------------------------------------------------
# AI Suggestions Queue
# ---------------------------------------------------------------------------

# How often (in seconds) the background worker polls the job table
# when no jobs are available.
WORKER_POLL_INTERVAL_SECONDS = 5

# Maximum number of consecutive worker loop failures before applying
# exponential backoff. After this threshold, sleep time doubles each cycle.
WORKER_MAX_CONSECUTIVE_FAILURES = 5

# Maximum number of times a failed job will be retried before being
# permanently marked as 'failed'.
MAX_JOB_RETRIES = 3

# How long (in minutes) a job may sit in 'processing' before it's considered
# orphaned (e.g. the worker that claimed it crashed mid-job) and reclaimed
# back to 'queued' by the next worker to poll.
STALE_PROCESSING_TIMEOUT_MINUTES = 15
