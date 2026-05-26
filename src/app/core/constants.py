"""
constants.py — Centralized configuration constants for the AI suggestion system.

All tunable values for the suggestion queue, background worker, and
context retrieval are defined here. Import from this module instead
of hardcoding values in business logic.
"""

# ---------------------------------------------------------------------------
# AI Suggestions Queue
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Context Retrieval (Translation Memory)
# ---------------------------------------------------------------------------

# Total number of context verse pairs (source + target) to include
# in the Translation Memory prompt sent to the LLM.
MAX_CONTEXT_VERSES_TOTAL = 50

# Of the total, how many slots are reserved for FTS (lexical similarity)
# matches. The remainder is filled by proximity/genre-based matches.
MAX_CONTEXT_VERSES_FTS = 25
