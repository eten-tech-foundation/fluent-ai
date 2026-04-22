#!/bin/bash
# Seed: initial admin API key
# Runs as part of docker-entrypoint-initdb.d on first DB start
# Requires ADMIN_API_KEY_HASH to be set in the db container environment

set -e

if [ -z "$ADMIN_API_KEY_HASH" ]; then
    echo "WARNING: ADMIN_API_KEY_HASH is not set — skipping admin API key seed."
    exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    INSERT INTO ai.api_keys (
        id,
        key_hash,
        name,
        permissions,
        is_active,
        owner_user_id,
        owner_org_id,
        created_at,
        expires_at
    )
    VALUES (
        gen_random_uuid(),
        '$ADMIN_API_KEY_HASH',
        'Seed Admin Key',
        ARRAY['admin'],
        TRUE,
        NULL,
        NULL,
        now(),
        NULL
    )
    ON CONFLICT (key_hash) DO NOTHING;
SQL

echo "Admin API key seeded successfully."