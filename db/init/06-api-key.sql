-- Migration: create ai.api_keys
-- Schema owner: ai service (fluent-ai)
-- Run as: migrations user
-- -------------------------------------------------------

CREATE TABLE IF NOT EXISTS ai.api_keys (
    id              UUID         NOT NULL DEFAULT gen_random_uuid(),
    key_hash        TEXT         NOT NULL,
    name            VARCHAR(255) NOT NULL,
    permissions     TEXT[]       NOT NULL DEFAULT '{}',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    owner_user_id   INTEGER      NULL,
    owner_org_id    INTEGER      NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ  NULL,

    CONSTRAINT pk_api_keys PRIMARY KEY (id),
    CONSTRAINT uq_api_keys_key_hash UNIQUE (key_hash)
);

-- Index for the hot path: validate incoming key by hash
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash
    ON ai.api_keys (key_hash)
    WHERE is_active = TRUE;

-- Grant DML to ai_user (owns ai schema)
GRANT SELECT, INSERT, UPDATE, DELETE ON ai.api_keys TO ai_user;