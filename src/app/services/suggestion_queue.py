# suggestion_queue.py — REMOVED
#
# This module was orphaned after the merge. The queueing logic for AI
# suggestion jobs is handled by the fluent-api (Node.js) side, which
# inserts jobs directly into ai.ai_suggestion_jobs via Drizzle ORM.
#
# The fluent-ai side only CONSUMES those jobs via the worker loop in
# app/worker/suggestion_processor.py.
#
# This file is intentionally empty and should be deleted.
