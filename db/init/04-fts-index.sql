-- =================================================================
-- Full Text Search (FTS) GIN Indexes for bible_texts
--
-- These indexes accelerate the FTS queries used by the AI context
-- retrieval service (context_retrieval.py) to find lexically similar
-- verses for Translation Memory prompts.
--
-- Two configs are indexed:
--   'english' — stemmed search for English source bibles
--   'simple'  — tokenize-only fallback for all other languages
--              (Gujarati, Hindi, niche African languages, etc.)
--
-- Must run AFTER 03-fluent-api-schema.sql (which creates bible_texts).
-- =================================================================

CREATE INDEX IF NOT EXISTS idx_bible_texts_text_fts_english
    ON public.bible_texts
    USING gin(to_tsvector('english', text));

CREATE INDEX IF NOT EXISTS idx_bible_texts_text_fts_simple
    ON public.bible_texts
    USING gin(to_tsvector('simple', text));
