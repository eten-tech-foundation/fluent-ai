# Code map

Where things live in `src/app/` and what each part calls. How the layers are shaped is in
[architecture.md](architecture.md), the rules the code relies on are in
[domain-rules.md](domain-rules.md), and setup is in the [README](../README.md).

## Outside this repo

- [fluent-api](https://github.com/eten-tech-foundation/fluent-api) is the only caller. It sends
  its key (`FLUENT_AI_KEY` on its side) in the `X-API-Key` header to `FLUENT_AI_URL` plus
  `FLUENT_AI_API_PREFIX`, which is empty because the routes here are served at the root. Its AI
  trigger worker calls `POST /suggestions`, its `POST /ai/tools/greek-room/repeated-words` route
  calls `POST /tools/greek-room/repeated-words`, and its `/ai/tts/generate` and
  `/ai/tts/audio/{file}` routes mirror `POST /tts/generate` and `GET /tts/audio/{file}`. Keys are
  made with an admin key through the `/api-keys` routes, as
  [docs/guides/api-keys.md](guides/api-keys.md) explains.
- The worker calls fluent-api back on `POST /ai-suggestions/internal/context` and
  `POST /ai-suggestions/internal/results`, at `API_BASE_URL`, with `API_SERVICE_KEY` as a bearer
  token (`src/app/worker/suggestion_processor.py`). It is the only code here that calls fluent-api.
  fluent-api's side of the flow is in its
  [ai-suggestions-workflow.md](https://github.com/eten-tech-foundation/fluent-api/blob/main/docs/ai-suggestions-workflow.md).
- Google Gemini is the only model provider. Text goes through `GoogleGeminiClient` in
  `src/app/core/ai_clients/google_gemini.py` (`GOOGLE_AI_API_KEY`, `GOOGLE_AI_MODEL`) and speech
  through `GeminiTtsProvider` in `src/app/services/tts/gemini_provider.py` (`TTS_MODEL`,
  `TTS_VOICE`). `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are settings that nothing reads.
- Greek Room is the `greekroom` package from PyPI, and it runs in the process. Its list of
  legitimate repeated pairs ships inside the package.
- Speech clips live in Cloudflare R2, reached through boto3 (`src/app/services/tts/artifacts.py`),
  and are compressed with ffmpeg (`src/app/services/tts/compression.py`), which the Docker images
  install from Alpine. The bucket's public domain, `TTS_PUBLIC_AUDIO_BASE_URL`, serves the
  compressed clips. fluent-web's
  [source-tts-operations.md](https://github.com/eten-tech-foundation/fluent-web/blob/main/docs/features/source-tts/source-tts-operations.md)
  is the deploy checklist.
- In Postgres this service owns the `ai` schema and nothing else: `ai.api_keys`, `ai.jobs` and
  Alembic's `ai.alembic_version`. `scripts/bootstrap.py` creates the `ai_user` and `ai_migrator`
  roles and grants them nothing outside `ai`. Data that fluent-api owns comes over HTTP, as
  [api-data-dependencies.md](api-data-dependencies.md) and fluent-platform's
  [db-ownership-separation](https://github.com/eten-tech-foundation/fluent-platform/tree/main/docs/features/db-ownership-separation)
  explain.
- GitHub Actions builds every commit on `main` once and deploys that image to Azure App Service:
  dev on merge, then QA and production by hand. The
  [deployment runbooks](runbooks/deployment/README.md) cover each step.

## App shell

- `src/app/main.py` creates the app, adds `RequestIDMiddleware` and `LoggingMiddleware`, registers
  the exception handlers, includes `src/app/routers/admin.py` and `src/app/api/v1/router.py`, and
  defines `GET /` and `GET /health`. Its lifespan builds the Greek Room service, starts the
  suggestion worker when `ENABLE_SUGGESTION_WORKER` is on, and on shutdown stops speech
  generations, then the worker.
- `src/app/config.py`: `Settings` and `get_settings()`. `ENVIRONMENT` picks the env file
  (`.env.prod` in production, otherwise `.env.dev` or `.env`), and only the exact value
  `production` turns on the production checks. `.env.example` lists the variables, and deploys set
  them as App Service settings.
- `src/app/dependencies.py`: what routers depend on (`get_db`, `require_api_key`,
  `require_admin`) and the shared clients and services (`get_google_gemini_client`,
  `get_repeated_words_service`, `get_tts_service`).
- `src/app/database.py`: the async engine, `AsyncSessionLocal` and `get_db`.
- `src/app/security/auth.py`: `require_api_key` and `require_admin`.
- `src/app/middleware/request_id.py`: `RequestIDMiddleware`, which sets and echoes `X-Request-ID`.
- `src/app/logging/`: `configure_logging`, `get_logger`, `LoggingMiddleware`, the formatters and
  `SensitiveDataFilter`.
- `src/app/errors/`: the exception types, `ErrorCode`, the `ErrorResponse` envelope and the
  handlers that `main.py` registers.
- `src/app/core/constants.py` (queue, worker and stats limits) and `src/app/core/ai_clients/` (the
  Gemini client). `src/app/core/config.py` and `src/app/core/exceptions.py` are placeholders, and
  `src/app/crud/` is empty.

## HTTP

`src/app/api/v1/router.py` is the current API. It mounts each module in
`src/app/api/v1/endpoints/` under a prefix, and `main.py` serves them at the root, not under
`/api/v1`. Every route there needs an API key, and Swagger UI at `/docs` documents them.

- `src/app/api/v1/endpoints/api_keys.py`: `POST /api-keys/`, `GET /api-keys/`,
  `PATCH /api-keys/{key_id}` and `DELETE /api-keys/{key_id}`, which need an admin key, and
  `GET /api-keys/me`, over `src/app/services/api_key.py`. Operators call them, not fluent-api.
- `src/app/api/v1/endpoints/greek_room.py`: `POST /tools/greek-room/repeated-words`, which runs
  `RepeatedWordsService` inside the request and answers with the `ToolJobResponse` envelope.
  fluent-api calls it for fluent-web's checks panel.
- `src/app/api/v1/endpoints/suggestions.py`: `POST /suggestions`, which queues suggestion jobs in
  `ai.jobs` through `src/app/services/suggestions.py`. fluent-api's AI trigger worker calls it.
- `src/app/api/v1/endpoints/jobs.py`: `GET /jobs/stats`, the `ai.jobs` health gauge from
  `src/app/services/jobs.py`, for operators and alerting.
- `src/app/api/v1/endpoints/translations.py`: `POST /translations/translate`, a synchronous
  Gemini translation of the verses in the request, through `TranslationService`. Nothing in
  fluent-api or fluent-web calls it.
- `src/app/api/v1/endpoints/tts.py`: `POST /tts/generate` and `GET|HEAD /tts/audio/{file}`, over
  `TtsService`. fluent-api mirrors them under `/ai/tts`.

`src/app/routers/admin.py` is the older, unversioned `/admin` router, scaffolding from early
development that nothing calls (see [Auth](domain-rules.md#auth)). New routes go in
`src/app/api/v1/endpoints/`.

## Worker and jobs

- Only AI suggestions, for verses and for pericope headings, are `ai.jobs` rows.
  `src/app/worker/suggestion_processor.py` is the whole worker: `worker_loop` requeues stale rows,
  claims the next one and backs off on errors, and `process_job` gets the context from fluent-api,
  calls Gemini through `TranslationService`, sends the results and keeps the retry count. The
  lifespan in `main.py` starts it.
- `src/app/services/suggestions.py`: `enqueue_suggestion_jobs` and `_dedup_key`, behind
  `POST /suggestions`.
- `src/app/services/translation_service.py`: `TranslationService` builds the verse and heading
  prompts and checks Gemini's answer. The worker and `POST /translations/translate` share it.
- `src/app/services/jobs.py`: `get_job_stats`, behind `GET /jobs/stats`.
- `src/app/core/constants.py`: the poll interval, the retry count, the stale timeout, the batch
  size, the failure detail limit and the stats window.
- Repeated words run inside the request, and speech clips are generated in the process by
  `TtsService`, so neither has a row in `ai.jobs`.

## Services, CRUD and models

- `src/app/services/api_key.py`: key generation and hashing, create, lookup by hash or id, list,
  update and revoke.
- `src/app/services/greek_room/repeated_words.py`: `RepeatedWordsService`, the only module that
  knows `greekroom`'s request and response shapes.
- `src/app/services/tts/`: `recipe.py` (the recipe and its HMAC name), `artifacts.py` (the R2
  store), `generation.py` (the generation heap, admission and listeners), `service.py`
  (`TtsService`: `generate`, the audio route's steps, the compression tail and shutdown),
  `provider.py` and `gemini_provider.py` (the provider interface and Gemini), `compression.py`
  (ffmpeg) and `wav.py` (the streaming WAV header).
- `src/app/schemas/`: request and response models, one file per area. `tool_job.py` is the
  envelope of the repeated words route, `translations.py` holds the model input and output types,
  and `tts.py` the strict TTS request.
- `src/app/models/api_key.py` and `src/app/models/job.py`: the two tables, `ai.api_keys` and
  `ai.jobs`.
- `src/app/crud/` is empty. Queries live in the services and the worker.

## Database, migrations and seeds

- `src/app/db/base.py`: `OwnedBase` and the model imports Alembic needs.
- `src/app/db/migrations/`: `env.py`, which only sees the `ai` schema and connects with
  `MIGRATIONS_DATABASE_URL` or `DATABASE_URL`, and three revisions in `versions/`: the API keys
  table, the jobs table and the jobs status check.
- `src/app/db/seeds/`: `seed_admin_api_keys` in `api_keys.py`, run by `runner.py` through
  `python -m app.db.seeds`. `src/app/db/scripts/setup.py` runs the migrations, then the seeds
  (`./fai.sh db:init`).
- `scripts/bootstrap.py`: creates the roles, the `ai` schema and the grants, connecting as the
  superuser in `BOOTSTRAP_DATABASE_URL`.
- `docker-entrypoint.sh` runs the bootstrap, the migrations and the seeds every time the
  development container starts, then `fastapi dev`. Deploys only run `alembic upgrade head`
  (`.github/workflows/deploy.yml`), and the production `Dockerfile` starts uvicorn with one worker.

## Tests and scripts

- `tests/`: one suite per endpoint module in `tests/api/v1/`, the TTS suites in `tests/tts/` (with
  fakes for S3, the provider and the encoder in `tests/tts/fakes.py`), and suites for errors,
  logging, the lifespan, the seeds and the key service. `tests/conftest.py` gives a `TestClient`
  with `get_db` replaced and the worker off. `tests/api/v1/test_projects.py` is a comment block for
  routes that were removed and holds no tests.
- `src/tests/`: the suggestions endpoint and service, the worker (`src/tests/worker/`, on SQLite
  through its `conftest.py`), the heading prompt, the Gemini client, the settings and `/health`.
- `tests/tts/test_real_smoke.py` calls the real Gemini and R2 and costs money, so it only runs
  with `TTS_SMOKE_REAL=1` (the `real_infra` marker).
- `scripts/smoke_repeated_words.py` probes a running service's repeated words route over HTTP
  (`./fai.sh run python scripts/smoke_repeated_words.py`), and `scripts/check-docs-structure.sh`
  is the docs check CI runs.

## Feature docs

`docs/features/` holds the designs and plans behind most features. Some status lines there are out
of date, so check the code before you rely on one.

- `docs/features/ai-suggestions/`: `heading-jobs.md` (pericope heading jobs on `POST /suggestions`)
  and the two July 2026 review-fix plans for the suggestion worker.
- `docs/features/ai-jobs-health/design.md`: `GET /jobs/stats` and the recommended failure alert.
- `docs/features/source-tts/source-tts-capacity.md`: how to size the TTS limits for a container.
- `docs/features/greek-room-integration/`: the summary, the pitch and the decisions behind the
  repeated words integration.
- `docs/features/http-decoupling-transition/plan.md`: the move from reading fluent-api's tables to
  calling it over HTTP.
- `docs/features/app-service-deployment/design.md`: the App Service deployment that shipped.
  `docs/features/cicd-pipeline/plan.md` planned Azure Container Apps instead, and
  `docs/features/gitops-roadmap/design.md` is an earlier roadmap for the platform.
- `docs/features/fastapi-structure-standardization/plan.md`: the plan that added the placeholder
  modules [architecture.md](architecture.md) describes.
- Outside `features/`: `docs/guides/api-keys.md` (bootstrapping and operating keys),
  `docs/guides/dependabot-workflow.md`, `docs/runbooks/deployment/` and
  `docs/calver-versioning.md`.
