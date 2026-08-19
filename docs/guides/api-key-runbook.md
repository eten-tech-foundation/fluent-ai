# API key runbook (Fluent AI)

Repeatable, verified process for **bootstrapping** and **operating** API keys in
**Fluent AI** — across local dev, staging, and production. Written for any coding
agent, IDE assistant, or human contributor.

Covers three flows:

1. [Local development](#1-local-development) — zero setup, public dev key.
2. [Production bootstrap](#2-production-bootstrap) — seed the first admin key.
3. [Day-to-day key management](#3-day-to-day-key-management) — mint, inspect,
   update, revoke further keys using the admin key.

## Core principles

1. **Hash in env, raw in a secrets manager.** The application only ever sees the
   SHA-256 hash (`ADMIN_API_KEY_HASH`). The raw key lives outside the app — in
   AWS Secrets Manager, Doppler, Vault, 1Password, or whatever your deploy
   pipeline uses. Putting the raw key in `.env` defeats the entire design.
2. **Raw keys are one-shot.** `POST /api-keys/` returns `raw_key` exactly once
   in `ApiKeyCreated`. It is never stored and cannot be retrieved again. Lose
   it → revoke + recreate.
3. **`ENVIRONMENT=production` is a hard gate.** It (a) suppresses seeding of the
   public `fai_dev_admin` key, (b) forces `show_stack_traces=False`, and (c)
   refuses to boot if `SECRET_KEY` / `API_SERVICE_KEY` are still placeholder
   defaults. See `Settings._enforce_production_safety` in
   [`src/app/config.py`](../../src/app/config.py).
4. **Seeds are idempotent.** Every admin-key insert is guarded by
   `ON CONFLICT (key_hash) DO NOTHING`, so re-running on a populated DB is a
   no-op. Re-deploys do not rotate keys.
5. **Exactly one owner per key.** `ApiKeyCreate` enforces
   `owner_user_id XOR owner_org_id` via a Pydantic `model_validator`. A request
   with both or neither is rejected with 422. See
   [`src/app/schemas/api_key.py`](../../src/app/schemas/api_key.py).
6. **Admin is a permission, not a flag.** `permissions: ["admin"]` on a key
   grants access to `POST/PATCH/DELETE /api-keys/*` and `GET /api-keys/`. The
   `require_admin` dependency in
   [`src/app/security/auth.py`](../../src/app/security/auth.py) checks
   `"admin" in permissions`.

## How authentication works (one paragraph)

Every protected endpoint pulls the raw key from the `X-API-Key` header (query
param `api_key` is a fallback), SHA-256 hashes it, and looks up the
`key_hash` in `ai.api_keys` filtered by `is_active = true` and
`expires_at > now()` (or `NULL`). The raw key never touches the DB. The
matched `ApiKey` row is attached to `request.state.api_key` and returned from
the dependency for downstream use. See `require_api_key` in
[`src/app/security/auth.py`](../../src/app/security/auth.py) and
`get_api_key_by_hash` in
[`src/app/services/api_key.py`](../../src/app/services/api_key.py).

## 1. Local development

Nothing to do. The seed in
[`src/app/db/seeds/api_keys.py`](../../src/app/db/seeds/api_keys.py) inserts a
public dev admin key on every non-production container start:

| Field | Value |
|---|---|
| Raw key | `fai_dev_admin` |
| SHA-256 hash | `6deee1cf62652696bb0d4393b3c30c813face041a13a5216dfe8718505df34f5` |
| Name | `Dev Admin Key` |
| Permissions | `["admin"]` |
| Owner | `owner_user_id = 97` (placeholder, see TODO in seed file) |

```bash
./fai.sh setup          # copies .env.example → .env if missing
./fai.sh up             # starts DB on 5432 + AI service on 8200, runs seeds

# Verify the dev admin key works:
curl http://localhost:8200/api-keys/me -H "X-API-Key: fai_dev_admin"
```

`fai_dev_admin` is **public and intended for local development only**. It is
never seeded when `ENVIRONMENT=production`.

## 2. Production bootstrap

Goal: get one admin-enabled key into the production DB without ever putting
its raw value in the app environment.

### 2.1 Generate the raw key out-of-band

Do this on your laptop, in your secrets manager, or in CI — **not** on the
production host.

```bash
# 32 bytes of entropy, URL-safe, prefixed with the project namespace "fai"
RAW_KEY="fai_$(openssl rand -hex 32)"
printf '%s\n' "$RAW_KEY"
# → fai_<64 hex chars>

# Compute the SHA-256 hash the app will store:
printf '%s' "$RAW_KEY" | shasum -a 256 | awk '{print $1}'
# → <64 hex chars>
```

The `fai_` prefix matches `generate_raw_key()` in
[`src/app/services/api_key.py`](../../src/app/services/api_key.py) — keys
minted later via the API get this prefix automatically; for the seed key you
must add it yourself.

### 2.2 Store the raw key in your secrets manager

Wherever operators retrieve production credentials (AWS Secrets Manager,
Doppler, Vault, 1Password, etc.). This is the **only** copy of the raw key
outside the moment of generation. The app will never see it.

### 2.3 Configure the production environment

In `.env.prod` (the file `_get_env_file()` selects when
`ENVIRONMENT=production` — see
[`src/app/config.py`](../../src/app/config.py)):

```dotenv
ENVIRONMENT=production
ADMIN_API_KEY_HASH=<the 64-char hex hash from step 2.1>
SECRET_KEY=<a real secret, not the dev placeholder>
API_SERVICE_KEY=<a real service key, not the dev placeholder>
# ...plus DATABASE_URL, API_BASE_URL, AI provider keys, logging, etc.
```

The production safety validator will refuse to boot if `SECRET_KEY` or
`API_SERVICE_KEY` are still their dev defaults.

### 2.4 Deploy / restart the service

`docker-entrypoint.sh` runs `alembic upgrade head` and
`python -m app.db.seeds` on every container start before launching FastAPI.
The seed `seed_admin_api_keys` inserts the hash with
`permissions=["admin"]`, `is_active=True`, `owner_user_id=97`, guarded by
`ON CONFLICT (key_hash) DO NOTHING`. Re-deploys are safe.

### 2.5 Verify

```bash
# From a host with access to the production service:
curl https://<prod-host>/api-keys/me -H "X-API-Key: <RAW_KEY from secrets manager>"
# Expect 200 with the key's ApiKeyInfo (id, name, permissions: ["admin"], ...)
```

A 200 confirms the hash was seeded and the raw key in your secrets manager
matches it. A 401 means either the hash wasn't seeded (check
`ADMIN_API_KEY_HASH` and that the container actually started with
`ENVIRONMENT=production`) or the raw key you retrieved doesn't match the hash
(re-generate from the same source, or re-bootstrap).

### 2.6 Bootstrap checklist

- [ ] Raw key generated with `fai_` prefix, 32+ bytes of entropy
- [ ] Raw key stored in secrets manager (not in `.env`, not in git, not in chat)
- [ ] SHA-256 hash computed and set as `ADMIN_API_KEY_HASH` in `.env.prod`
- [ ] `ENVIRONMENT=production` set in `.env.prod`
- [ ] `SECRET_KEY` and `API_SERVICE_KEY` set to real values (not dev defaults)
- [ ] Container restarted; entrypoint logs show
      `Production admin API key seed created=True` (first deploy) or
      `created=False` (re-deploy)
- [ ] `GET /api-keys/me` with the raw key returns 200

## 3. Day-to-day key management

Once the bootstrap admin key exists, all further key management goes through
the API. No DB access required.

### 3.1 Mint a new key (admin only)

```bash
curl -X POST https://<prod-host>/api-keys/ \
  -H "X-API-Key: <ADMIN_RAW_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
        "name": "fluent-api prod",
        "permissions": [],
        "owner_user_id": 1
      }'
```

Response (`ApiKeyCreated`, HTTP 201):

```json
{
  "id": "uuid",
  "name": "fluent-api prod",
  "permissions": [],
  "raw_key": "fai_<...>",
  "created_at": "2026-08-19T...",
  "expires_at": null
}
```

**Save `raw_key` immediately** — it is never returned again. Put it wherever
the calling service retrieves its credentials (e.g. fluent-api's
`FLUENT_AI_URL` + key in its own secrets manager).

Notes:

- `permissions: ["admin"]` makes the new key itself an admin key. Use sparingly.
- Omit `expires_at` to use `API_KEY_DEFAULT_EXPIRY_DAYS` from config (default
  `None` = never expires). Pass an explicit ISO 8601 datetime to override.
- `owner_user_id` **or** `owner_org_id` — exactly one, must be `> 0`. Both or
  neither → 422.
- The placeholder `owner_user_id = 97` is used by the seeded admin keys until
  real admin user/org schemas land (tracked by `TODO(fluent-platform)` in
  [`src/app/db/seeds/api_keys.py`](../../src/app/db/seeds/api_keys.py)).

### 3.2 Inspect the current key

```bash
curl https://<prod-host>/api-keys/me -H "X-API-Key: <RAW_KEY>"
```

Returns `ApiKeyInfo` — never includes `raw_key` or `key_hash`. Any valid
(non-admin) key can call this.

### 3.3 List all keys (admin only)

```bash
curl https://<prod-host>/api-keys/ -H "X-API-Key: <ADMIN_RAW_KEY>"
```

Returns `list[ApiKeyInfo]` ordered by `created_at` descending.

### 3.4 Update a key (admin only)

```bash
curl -X PATCH https://<prod-host>/api-keys/<key_id> \
  -H "X-API-Key: <ADMIN_RAW_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"name": "renamed", "permissions": ["admin"], "expires_at": "2027-01-01T00:00:00Z"}'
```

All fields optional. Returns the updated `ApiKeyInfo`. 404 if `key_id` not
found.

### 3.5 Revoke a key (admin only)

```bash
curl -X DELETE https://<prod-host>/api-keys/<key_id> \
  -H "X-API-Key: <ADMIN_RAW_KEY>"
```

Returns HTTP 204. Revocation sets `is_active = False` — the row is retained
for audit (the `revoke_api_key` log line is emitted at WARNING level). The
next request using the revoked raw key gets 403
(`AuthorizationException`, `AUTHORIZATION_DENIED`, "API key has been
revoked."). This is distinct from an unknown key, which returns 401
`TOKEN_INVALID` — so callers can tell the difference between a typo and a
revocation.

**Revocation is the recovery path for a lost raw key** — there is no "show me
the key again" endpoint.

### 3.6 Rotate the bootstrap admin key

Because the seed is idempotent on `key_hash`, you cannot rotate by simply
changing `ADMIN_API_KEY_HASH` and restarting — the old row stays. To rotate:

1. Generate a new raw key + hash (step 2.1).
2. Store the new raw key in the secrets manager.
3. Update `ADMIN_API_KEY_HASH` in `.env.prod` to the new hash.
4. Restart the service — the new admin key is seeded alongside the old one.
5. Verify the new key via `GET /api-keys/me`.
6. Revoke the old admin key by its `id` via `DELETE /api-keys/{id}` (use the
   new key to authenticate). Confirm via `GET /api-keys/` that only the new
   admin key remains active.

## Endpoint reference

| Method | Path | Auth | Response model | Notes |
|---|---|---|---|---|
| `POST` | `/api-keys/` | admin | `ApiKeyCreated` (201) | Returns `raw_key` once |
| `GET` | `/api-keys/` | admin | `list[ApiKeyInfo]` | Ordered by `created_at` desc |
| `PATCH` | `/api-keys/{key_id}` | admin | `ApiKeyInfo` | 404 if not found |
| `DELETE` | `/api-keys/{key_id}` | admin | 204 | Soft-delete (`is_active=False`) |
| `GET` | `/api-keys/me` | any valid key | `ApiKeyInfo` | Inspect calling key |

Source: [`src/app/api/v1/endpoints/api_keys.py`](../../src/app/api/v1/endpoints/api_keys.py).

## Common errors

| Symptom | Likely cause | Fix |
|---|---|---|
| 401 `AUTHENTICATION_REQUIRED` | Missing `X-API-Key` header | Add the header |
| 401 `TOKEN_INVALID` | Raw key doesn't hash to any stored `key_hash` | Check the key was created / seeded; check for trailing whitespace or missing `fai_` prefix |
| 403 `AUTHORIZATION_DENIED` | Key revoked (`is_active=False`) | Mint a new key; or for the bootstrap admin, rotate via §3.6 |
| 403 `TOKEN_EXPIRED` | Key's `expires_at` is in the past | `PATCH` to extend `expires_at` (admin), or mint a new key |
| 403 `INSUFFICIENT_PERMISSIONS` | Key lacks `"admin"` permission | Use an admin key, or `PATCH` the key to add `["admin"]` (requires an existing admin) |
| 422 validation error | `owner_user_id` and `owner_org_id` both set or both unset | Set exactly one |
| Boot fails: "secret_key is still set to its insecure development default" | `ENVIRONMENT=production` but `SECRET_KEY` is the dev placeholder | Set a real `SECRET_KEY` in `.env.prod` |
| Boot fails: "api_service_key is still set to its insecure development default" | Same, for `API_SERVICE_KEY` | Set a real `API_SERVICE_KEY` in `.env.prod` |
| `fai_dev_admin` works in prod | `ENVIRONMENT` is not `production` | Set `ENVIRONMENT=production` and restart; then audit `ai.api_keys` for the dev row and revoke it |

## Related files

- [`src/app/config.py`](../../src/app/config.py) — `Settings.admin_api_key_hash`,
  `api_key_default_expiry_days`, production safety validator
- [`src/app/db/seeds/api_keys.py`](../../src/app/db/seeds/api_keys.py) — admin
  key seeding (dev + prod paths)
- [`src/app/schemas/api_key.py`](../../src/app/schemas/api_key.py) —
  `ApiKeyCreate` / `ApiKeyCreated` / `ApiKeyInfo` / `ApiKeyUpdate`
- [`src/app/services/api_key.py`](../../src/app/services/api_key.py) — key
  generation, hashing, CRUD
- [`src/app/security/auth.py`](../../src/app/security/auth.py) —
  `require_api_key`, `require_admin` dependencies
- [`src/app/api/v1/endpoints/api_keys.py`](../../src/app/api/v1/endpoints/api_keys.py)
  — route handlers
- [`tests/api/v1/test_api_keys.py`](../../tests/api/v1/test_api_keys.py) —
  endpoint tests (authoritative examples of request/response shapes)
