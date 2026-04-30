#!/bin/bash
# Seed: admin API keys
# Runs as part of docker-entrypoint-initdb.d on first DB start
#
# Always inserts the fixed development key (fai_dev_admin).
# If ADMIN_API_KEY_HASH is set, also inserts a named production key.

set -e

# ── Dev key (always seeded) ────────────────────────────────────────────────
# Raw key:  fai_dev_admin
# Hash:     sha256("fai_dev_admin")
DEV_KEY_HASH="6deee1cf62652696bb0d4393b3c30c813face041a13a5216dfe8718505df34f5"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    INSERT INTO ai.api_keys (
        id, key_hash, name, permissions, is_active,
        owner_user_id, owner_org_id, created_at, expires_at
    )
    VALUES (
        gen_random_uuid(),
        '$DEV_KEY_HASH',
        'Dev Admin Key',
        ARRAY['admin'],
        TRUE,
        NULL,
        NULL,
        now(),
        NULL
    )
    ON CONFLICT (key_hash) DO NOTHING;
SQL

echo "Dev API key seeded (raw key: fai_dev_admin)."

# ── Production key (only when ADMIN_API_KEY_HASH is provided) ─────────────
if [ -n "$ADMIN_API_KEY_HASH" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
        INSERT INTO ai.api_keys (
            id, key_hash, name, permissions, is_active,
            owner_user_id, owner_org_id, created_at, expires_at
        )
        VALUES (
            gen_random_uuid(),
            '$ADMIN_API_KEY_HASH',
            'Admin Key',
            ARRAY['admin'],
            TRUE,
            NULL,
            NULL,
            now(),
            NULL
        )
        ON CONFLICT (key_hash) DO NOTHING;
SQL
    echo "Production admin API key seeded."
fi
