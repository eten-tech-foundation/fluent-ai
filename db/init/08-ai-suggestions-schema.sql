-- =================================================================
-- AI Suggestions Schema — Tables owned by the AI service
--
-- These tables live in the 'ai' schema because they are created
-- and managed exclusively by fluent-ai (ai_user / role_ai_data).
--
-- The AI service has full DML (INSERT/UPDATE/DELETE) on the 'ai'
-- schema, but only SELECT access on the 'public' schema.
--
-- Schema division:
--   public.*  → Platform tables (projects, bible_texts, etc.)
--               Owned by fluent-server. AI has READ-ONLY access.
--   ai.*      → AI-owned tables (suggestion jobs, suggestions, api_keys)
--               Owned by fluent-ai. Full read-write access.
--   pgboss.*  → Job queue for the web API (shared).
--
-- Must run AFTER 01-init-db.sql (which creates the 'ai' schema
-- and grants DML to role_ai_data).
-- =================================================================

-- -----------------------------------------------------------------
-- ai.ai_suggestion_jobs — Background job queue for AI translations
--
-- Each row represents a request to generate AI translation
-- suggestions for a contiguous range of verses. The background
-- worker polls this table for 'queued' jobs.
--
-- Lifecycle: queued → processing → completed | failed
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai.ai_suggestion_jobs (
    id              SERIAL PRIMARY KEY,
    project_unit_id INTEGER     NOT NULL,
    bible_id        INTEGER     NOT NULL,
    book_code       VARCHAR(50) NOT NULL,
    chapter_number  INTEGER     NOT NULL,
    verse_start     INTEGER     NOT NULL,
    verse_end       INTEGER     NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
    retry_count     INTEGER     NOT NULL DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
    updated_at      TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);

-- Index for the worker polling query (find oldest queued job)
CREATE INDEX IF NOT EXISTS idx_ai_suggestion_jobs_status_created
    ON ai.ai_suggestion_jobs (status, created_at ASC);

-- Index for deduplication queries (check if a verse range is already queued)
CREATE INDEX IF NOT EXISTS idx_ai_suggestion_jobs_dedup
    ON ai.ai_suggestion_jobs (project_unit_id, bible_id, book_code, chapter_number);

-- -----------------------------------------------------------------
-- ai.ai_suggestions — Completed AI translation suggestions
--
-- Each row is one AI-generated translation for a single verse.
-- The client polls these via GET /project-units/{id}/suggestions.
-- -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai.ai_suggestions (
    id              SERIAL PRIMARY KEY,
    bible_text_id   INTEGER     NOT NULL,
    project_unit_id INTEGER     NOT NULL,
    suggested_text  TEXT        NOT NULL,
    model_info      VARCHAR(100),
    created_at      TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
);

-- Index for the client polling query
CREATE INDEX IF NOT EXISTS idx_ai_suggestions_lookup
    ON ai.ai_suggestions (project_unit_id, bible_text_id);

-- Unique indexes for deduplication (used by fluent-api's ON CONFLICT DO NOTHING)
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_jobs_range
    ON ai.ai_suggestion_jobs (project_unit_id, book_code, chapter_number, verse_start, verse_end);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_suggestions_per_text_unit
    ON ai.ai_suggestions (bible_text_id, project_unit_id);

-- -----------------------------------------------------------------
-- Cross-Schema Grants
--
-- fluent-api (web_user / role_web_data) needs limited access to
-- these ai-schema tables:
--   - INSERT into ai_suggestion_jobs  (to enqueue work)
--   - SELECT from ai_suggestion_jobs  (to check job status)
--   - SELECT from ai_suggestions      (to serve results to the client)
--
-- fluent-ai (ai_user / role_ai_data) already has full DML on the
-- entire ai schema via the grants in 01-init-db.sql.
-- -----------------------------------------------------------------
GRANT SELECT, INSERT ON ai.ai_suggestion_jobs TO role_web_data;
GRANT USAGE, SELECT ON SEQUENCE ai.ai_suggestion_jobs_id_seq TO role_web_data;

GRANT SELECT ON ai.ai_suggestions TO role_web_data;

