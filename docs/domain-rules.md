# Domain rules and review checks

These are the rules the current code and tests rely on. Each one names the code that holds it and
a test that pins it, or says that no test covers it, so a change can be checked against it. If a
change has to break a rule, say so in the PR and update this file in the same PR.

Each rule states the behavior we want. Where the code differs, the rule says so:

- **Exception:** the code differs on purpose, for the reason given.
- **Grandfathered:** the code differs and should change. Every grandfathered item is listed in
  the follow-on ticket linked from the PR that added this file.

Tests are cited as `path::test_name`, and pytest runs one with
`uv run pytest 'path::test_name'`. How the modules are shaped is in
[architecture.md](architecture.md), not here.

Three of these look like bugs but are intentional. A job fails for good on any 4xx from
fluent-api, a completed job never runs again for the same request (both under [Jobs](#jobs)), and
fluent-ai never checks a Bible's licence before speech (see
[Content protection](#content-protection)).

## Auth

fluent-ai's callers are services holding a key from `ai.api_keys`. In practice that is fluent-api,
which sends one key on every call. [docs/guides/api-keys.md](guides/api-keys.md) has the steps for
operating keys; these are the behaviors behind them.

- Every route in the v1 router needs a key in the `X-API-Key` header. `require_api_key`
  (`src/app/security/auth.py`) hashes it, looks it up in `ai.api_keys`, and answers 401 when the
  key is missing or unknown and 403 when it is revoked or expired. A 401 waits half a second
  before it goes out (`_handle_authentication_exception` in `src/app/errors/handlers.py`), to slow
  down key guessing. Tests:
  `tests/api/v1/test_api_keys.py::TestAuthBehaviour::test_unknown_key_returns_401`,
  `tests/api/v1/test_api_keys.py::TestAuthBehaviour::test_revoked_key_record_returns_403`,
  `tests/api/v1/test_api_keys.py::TestAuthBehaviour::test_expired_key_returns_403`,
  `tests/api/v1/test_jobs.py::test_missing_api_key_is_rejected`. No test covers the delay.
- `GET /` and `GET /health` need no key, and neither do FastAPI's `/docs`, `/redoc` and
  `/openapi.json`. The deploy workflows poll `/health` until its `commit` is the one they shipped,
  so its keys have to stay as they are. Tests: `src/tests/test_health.py::test_health_reports_healthy`,
  `src/tests/test_health.py::test_health_identifies_the_running_build`.
- `admin` is the only permission any code checks. `require_admin` guards the `/api-keys` routes
  except `GET /api-keys/me`, and the other v1 routes accept any active key. Tests:
  `tests/api/v1/test_api_keys.py::TestCreateKey::test_non_admin_returns_403`,
  `tests/api/v1/test_api_keys.py::TestListKeys::test_non_admin_returns_403`,
  `tests/api/v1/test_api_keys.py::TestGetMyKey::test_returns_200_with_key_info`.
  **Grandfathered:** the older `/admin` router (`src/app/routers/admin.py`) is scaffolding from
  early development, with placeholder stats and health routes and a manual Gemini check. Nothing
  calls it, and it should be removed. No test covers it.
- `POST /api-keys/` makes a key from `fai_` and 32 random bytes, stores only its SHA-256 and
  returns the raw key once. No other response carries the raw key or the hash. A key belongs to
  exactly one owner, a user id or an org id, and fluent-ai can't check either id. When the request
  sets no expiry, `API_KEY_DEFAULT_EXPIRY_DAYS` applies if it is set, and otherwise the key never
  expires. Tests: `tests/api/v1/test_api_keys.py::TestCreateKey::test_raw_key_absent_from_schema_after_creation`,
  `tests/api/v1/test_api_keys.py::TestListKeys::test_no_raw_key_or_hash_in_response`,
  `tests/api/v1/test_api_keys.py::TestGetMyKey::test_no_raw_key_or_hash_in_response`,
  `tests/api/v1/test_api_keys.py::TestCreateKey::test_both_owners_returns_422`,
  `tests/api/v1/test_api_keys.py::TestCreateKey::test_no_owner_returns_422`. No test pins the key
  format, the hash or the default expiry: `tests/test_services_api_key.py` replaces `ApiKey` with a
  mock that already holds the expected value.
- Revoking (`DELETE /api-keys/{key_id}`) sets `is_active` to false and keeps the row, and nothing
  turns a key back on. There is no rotation endpoint. Rotating means making a new key, moving the
  caller to it and revoking the old one, and since keys can overlap there is no gap.
  `PATCH /api-keys/{key_id}` changes the name, the permissions or the expiry. Tests:
  `tests/api/v1/test_api_keys.py::TestRevokeKey::test_returns_204`,
  `tests/test_services_api_key_query.py::test_get_api_key_by_hash_returns_inactive_key`,
  `tests/api/v1/test_api_keys.py::TestPatchKey::test_returns_updated_record`. **Grandfathered:**
  `PATCH` can't clear an expiry, because null means "no change", and it doesn't validate the name,
  so an empty name is saved and one over 255 characters fails with a 500. No test covers either.
- The seeds in `src/app/db/seeds/api_keys.py` add the development admin key outside production,
  and an admin key from `ADMIN_API_KEY_HASH` when that is set. They only insert, so a seeded key
  that was revoked stays revoked. Tests: `tests/test_db_seeds.py::test_dev_key_skipped_in_production`,
  `tests/test_db_seeds.py::test_admin_key_seeded_when_hash_provided`,
  `tests/test_db_seeds.py::test_upsert_reports_not_created_when_rowcount_zero`. **Grandfathered:**
  deploys never run the seeds. The production image starts uvicorn and
  `.github/workflows/deploy.yml` only runs the migrations, so the `ADMIN_API_KEY_HASH` app setting
  does nothing until someone runs the seed against that database by hand, while the API keys guide
  says the container does it on every start. Either the deploy should seed or the guide should give
  the manual step. No test covers it.
- fluent-api calls in with its key in `X-API-Key` and treats any answer that isn't 2xx as the AI
  service being down, so a revoked or expired key looks like an outage on its side. The worker
  calls back with a different key: `API_SERVICE_KEY` as a bearer token, which must equal
  fluent-api's `AI_INBOUND_SERVICE_KEY`. Production refuses to start with the development default
  of `API_SERVICE_KEY` or `SECRET_KEY`. Tests:
  `src/tests/test_config.py::test_production_settings_rejects_default_api_service_key`,
  `src/tests/test_config.py::test_production_settings_rejects_default_secret_key`, and
  `src/tests/worker/test_heading_processor.py::test_heading_job_uses_full_context_and_pushes_only_heading`
  for the bearer on the context call.
- In production `SHOW_STACK_TRACES` is forced off, and an unhandled exception answers with a fixed
  message. Tests: `tests/test_logging.py::TestProductionSafety::test_stack_traces_forced_off_in_production`,
  `tests/test_error_handlers.py::TestSecurityProperties::test_unhandled_exception_message_sanitized`.

## Jobs

AI suggestions are rows in `ai.jobs`, and the worker in `src/app/worker/suggestion_processor.py`
runs them. fluent-api's side of the flow is in its
[ai-suggestions-workflow.md](https://github.com/eten-tech-foundation/fluent-api/blob/main/docs/ai-suggestions-workflow.md),
pericope heading jobs are in [heading-jobs.md](features/ai-suggestions/heading-jobs.md), and the
stats endpoint and its alert are in the [ai-jobs-health design](features/ai-jobs-health/design.md).
The repeated word check and speech don't use `ai.jobs`: the first runs inside the request, and the
second has its own generation heap (see [Text to speech](#text-to-speech)).

- A job is an `ai.jobs` row with `task_type` `ai_suggestion` and a `status` of `queued`,
  `processing`, `completed` or `failed`, which a check constraint holds. A heading job is the same
  task type with `pericopeNumber` and `pericopeSetId` in its payload. The payload is the trigger
  request: ids and numbers, no text. Tests:
  `src/tests/test_suggestions_service.py::test_heading_jobs_keep_separate_dedup_identity_and_persist_metadata`,
  `src/tests/worker/test_suggestion_processor.py::test_job_status_accepts_all_four_valid_values`.
  **Grandfathered:** the worker never reads `task_type`, so it would run any row as a suggestion,
  while the model, the [HTTP decoupling plan](features/http-decoupling-transition/plan.md) and the
  health design expect more task types. No test covers it.
- `POST /suggestions` takes an array of at most `MAX_SUGGESTION_BATCH_SIZE` (100) requests and
  validates every item before it writes anything, so one bad item rejects the whole array. It
  answers 200 with `queued`, `requeued` and `skipped` counts, not job ids. Tests:
  `src/tests/api/v1/test_suggestions.py::test_trigger_suggestions_rejects_batch_over_max_size`,
  `src/tests/api/v1/test_suggestions.py::test_trigger_suggestions_returns_structured_counts`,
  `src/tests/test_suggestions_service.py::test_suggestion_trigger_request_rejects_inverted_verse_range`.
  No test covers the whole-array rejection.
- Enqueueing dedups by content (`_dedup_key` in `src/app/services/suggestions.py`). A verse job's
  key is the unit, Bible, book, chapter and verse range, and a heading job's key hashes the whole
  request. Sending a queued, processing or completed job again is skipped, so a completed job is
  never redone, on purpose (the comment in `enqueue_suggestion_jobs`). Sending a failed job again
  requeues it with its retry count and error cleared, which is how a failed job is re-triggered
  ([fluent-ai#87](https://github.com/eten-tech-foundation/fluent-ai/pull/87)). Tests:
  `src/tests/test_suggestions_service.py::test_enqueue_reports_duplicates_skipped`,
  `src/tests/test_suggestions_service.py::test_retrigger_of_failed_job_requeues_it`,
  `src/tests/test_suggestions_service.py::test_retrigger_of_unfailed_job_is_skipped_untouched`,
  `src/tests/test_suggestions_service.py::test_retrigger_listing_a_failed_job_twice_requeues_it_once`.
  **Grandfathered:** a heading job that completes without generating anything, because fluent-api
  had no heading to suggest at that moment, stays completed, so the same request sent later is
  skipped for good. No test covers it.
- The worker runs one job at a time per process. Each pass first requeues `processing` rows older
  than `STALE_PROCESSING_TIMEOUT_MINUTES` (15), then claims the oldest queued row with
  `FOR UPDATE SKIP LOCKED` and commits `processing` at once, so several instances can share the
  table. It sleeps `WORKER_POLL_INTERVAL_SECONDS` only when the queue is empty. Test:
  `src/tests/worker/test_suggestion_processor.py::test_reclaim_stale_jobs_requeues_orphaned_processing_job`.
  No test covers the claim. **Grandfathered:** the stale requeue doesn't count as a retry, so a job
  that brings the worker down every time comes back forever, and a job still running after the
  timeout can be claimed again by another instance.
- `updated_at` records when a row entered its current status, and the stale requeue and
  `GET /jobs/stats` rely on that. **Exception:** the timestamps are naive UTC and the code assumes
  the database runs in UTC, because tz-aware comparisons failed on every poll and fixing the
  columns needs a migration
  ([2026-07-07 review-fix plan](features/ai-suggestions/2026-07-07-plan-followup-review-fixes.md)).
  Tests: `src/tests/worker/test_suggestion_processor.py::test_updated_at_changes_on_status_update`,
  `src/tests/test_suggestions_service.py::test_requeue_refreshes_updated_at`.
- A job pulls its context from fluent-api (`POST /ai-suggestions/internal/context` on
  `API_BASE_URL`, with a 30 second timeout), asks Gemini, checks the answer and pushes it to
  `POST /ai-suggestions/internal/results`. It is completed only after that push answers 2xx. A
  verse answer keeps only the items whose verse was requested, and a heading must pass
  `HeadingTranslationResult` in `src/app/schemas/translations.py`: one plain line of 1 to 300
  UTF-16 units. A job also fails, without retries, when fluent-api finds no source verses or when
  every item was dropped. Tests:
  `src/tests/worker/test_heading_processor.py::test_verse_job_keeps_existing_context_and_results_contract`,
  `src/tests/worker/test_heading_processor.py::test_heading_job_uses_full_context_and_pushes_only_heading`,
  `src/tests/worker/test_suggestion_processor.py::test_process_job_skips_malformed_verse_id_instead_of_failing_job`,
  `src/tests/worker/test_suggestion_processor.py::test_process_job_fails_when_all_items_are_dropped`,
  `src/tests/test_heading_translation.py::test_heading_service_rejects_unsafe_output_for_worker_retry`.
  **Grandfathered:** two items for the same verse are both pushed, fluent-api's upsert rejects the
  batch, and the job retries until it fails. No test covers it.
- Retryable errors requeue the job with `Retry n/3: <detail>` in `error_message`: a 5xx, timeout or
  connection error from fluent-api, any Gemini error, or an answer that doesn't parse. After
  `MAX_JOB_RETRIES` (3) retries, four attempts in all, the job fails with
  `Permanently failed after 3 retries`. An invalid stored payload, a 4xx from fluent-api or heading
  context that doesn't match the job fails at once (`NonRetryableJobError`). Tests:
  `src/tests/worker/test_suggestion_processor.py::test_process_job_requeues_on_transient_failure_without_raising`,
  `src/tests/worker/test_suggestion_processor.py::test_process_job_marks_failed_after_max_retries`,
  `src/tests/worker/test_suggestion_processor.py::test_process_job_fails_immediately_on_4xx_from_fluent_api`,
  `src/tests/worker/test_heading_processor.py::test_invalid_or_mismatched_heading_context_fails_without_retries`.
  **Exception:** a 4xx is final even when its cause is configuration that can be fixed, such as a
  key mismatch. Once it is fixed, re-trigger the jobs
  ([2026-07-06 review-fix plan](features/ai-suggestions/2026-07-06-plan-review-fixes.md), Task 5).
  **Grandfathered:** retries have no delay, so a short fluent-api restart or a burst of Gemini
  errors uses up all four attempts within seconds. The Gemini call has no timeout either, so a call
  that hangs holds the process's only worker. No test covers either.
- `error_message` says why: the exception text or type, plus the upstream detail such as Gemini's
  error body or a validation cause, cut at `MAX_FAILURE_DETAIL_CHARS` (500). It is cleared when a
  worker starts the job. The ERROR lines `Job <id> permanently failed (non-retryable).` and
  `Job <id> permanently failed after 3 retries.` are what the recommended alert matches, so
  rewording them breaks it. Tests:
  `src/tests/worker/test_suggestion_processor.py::test_failure_detail_is_capped`,
  `src/tests/worker/test_suggestion_processor.py::test_permanent_failure_message_carries_external_service_detail`,
  `src/tests/worker/test_suggestion_processor.py::test_failure_message_names_exception_type_when_it_has_no_text`.
  No test covers the log lines.
- fluent-api never hears that a job failed, since its own queue job ended when `POST /suggestions`
  answered 2xx. Failures show only in `ai.jobs` and in `GET /jobs/stats`, which reads the table on
  every call: counts by status, over all time and over the last `window_hours` (1 to 720, 24 by
  default), the oldest row in each status, and the latest failure. It never returns a payload, and
  it redacts credentials and quoted input values in the failure text. `ai.jobs` keeps every row, so
  the lifetime counts only grow. Tests: `tests/api/v1/test_jobs.py::test_counts_jobs_by_status`,
  `tests/api/v1/test_jobs.py::test_recent_counts_only_jobs_that_changed_status_within_the_window`,
  `tests/api/v1/test_jobs.py::test_reports_oldest_backlog_and_newest_failure`,
  `tests/api/v1/test_jobs.py::test_response_never_contains_job_payloads`,
  `tests/api/v1/test_jobs.py::test_latest_failure_does_not_echo_payload_values`.
- The worker is an asyncio task in the web process, one per container, which the lifespan starts
  when `ENABLE_SUGGESTION_WORKER` is on (the default). Shutdown cancels it, and the job it was
  running waits for the stale requeue. No test covers the switch. **Grandfathered:** without
  `GOOGLE_AI_API_KEY` the task dies at startup with nothing in the logs, while the lifespan has
  logged that the worker started, and jobs pile up as queued. It should fail loudly. No test covers
  it.

## Text to speech

`POST /tts/generate` and `GET|HEAD /tts/audio/{file}` turn source text into speech. The design is
fluent-web's
[source-tts proposal](https://github.com/eten-tech-foundation/fluent-web/blob/main/docs/features/source-tts/source-tts-suggestion.md),
which the § numbers and T decisions in the code comments refer to, and sizing is in
[source-tts-capacity.md](features/source-tts/source-tts-capacity.md).

- A clip's name comes from its recipe. `build_recipe` (`src/app/services/tts/recipe.py`) fills in
  the default voice and format and drops `lang_code` when the provider ignores it, as Gemini does,
  and `artifact_hash` is the HMAC-SHA256 of the canonical recipe under `TTS_HASH_SECRET`, as 64
  lowercase hex characters. The text is never trimmed or changed, so two requests share a clip only
  when text, voice, model, format and recipe version all match. A change to what goes into a recipe
  needs a new `RECIPE_VERSION`. Tests:
  `tests/tts/test_recipe.py::TestArtifactHash::test_secret_participates`,
  `tests/tts/test_recipe.py::TestLangCodeNormalization::test_text_is_never_altered`,
  `tests/tts/test_recipe.py::TestFormatResolution::test_explicit_format_equal_to_the_default_dedups_with_omitting`,
  `tests/api/v1/test_tts.py::TestGenerateSuccess::test_lang_code_spellings_share_one_artifact`,
  `tests/tts/test_recipe.py::TestCanonicalRecipe::test_version_prefix_is_present_and_not_a_request_field`.
- `generate` only authorizes a clip. It writes the recipe to `requests/{hash}.json` in R2 with a
  conditional PUT, never calls the provider and answers with `audio_url` alone, so calling it again
  changes nothing (`TtsService.generate` in `src/app/services/tts/service.py`). The audio route
  only synthesizes a hash whose recipe is there, and any other name is a 404 that spends nothing.
  Tests: `tests/api/v1/test_tts.py::TestGenerateSuccess::test_generate_never_synthesizes`,
  `tests/api/v1/test_tts.py::TestGenerateSuccess::test_repeating_the_call_is_an_idempotent_no_op`,
  `tests/api/v1/test_tts.py::TestGenerateSuccess::test_response_carries_nothing_but_audio_url`,
  `tests/api/v1/test_tts_audio.py::TestNotFound::test_an_unauthorized_hash_is_a_404_and_spends_nothing`.
- fluent-ai owns the text limit, since fluent-api sets none. Empty or blank text is a 400
  `TTS_INVALID_REQUEST`, and text over `TTS_MAX_TEXT_LENGTH` code points (4,000 by default) is a
  400 `TTS_TEXT_TOO_LONG`, both before any hashing, storage or provider call. Unknown fields are a
  422. `TTS_MAX_TEXT_LENGTH` has to fit in `TTS_MAX_CLIP_BYTES` at 4,000 bytes of audio per
  character, or a long text is billed and then cut off mid-stream, and `TtsService` logs a warning
  when an override breaks that. Tests:
  `tests/api/v1/test_tts.py::TestValidation::test_whitespace_only_text_is_also_rejected`,
  `tests/api/v1/test_tts.py::TestValidation::test_one_character_over_the_maximum_is_rejected`,
  `tests/api/v1/test_tts.py::TestValidation::test_an_unknown_field_is_a_client_bug`,
  `tests/tts/test_service.py::TestLimitPairing::test_an_override_that_reopens_the_gap_is_logged`.
- In R2, under `TTS_R2_PREFIX`, each hash has `requests/{hash}.json` (the recipe),
  `audio/{hash}.ogg` or `audio/{hash}.mp3` (the compressed clip) and `receipts/{hash}.json` (size
  and duration). The recipe and the audio are written once with a conditional PUT, so the first
  writer wins, and fluent-ai never deletes them. Tests:
  `tests/tts/test_artifacts.py::TestKeyLayout::test_the_three_prefixes_live_under_the_configured_prefix`,
  `tests/tts/test_artifacts.py::TestConditionalPut::test_first_write_wins_and_reports_that_it_wrote`,
  `tests/tts/test_compression_tail.py::TestSkippingWork::test_losing_the_conditional_put_is_success_not_an_error`.
  **Grandfathered:** the compressed objects go up without `Cache-Control`, while the proposal
  expects immutable cache headers on them (§7.2 and §12.3). No test covers it.
- `audio_url` has two shapes. A cold one is relative to the `generate` URL (`audio/{hash}.wav`). A
  warm one is the absolute public URL of the compressed object, under `TTS_PUBLIC_AUDIO_BASE_URL`,
  and comes back when the recipe already existed and the object is there. Callers resolve it
  against the URL they called, so `/tts/generate` and `/tts/audio/{file}` must stay siblings, here
  and under fluent-api's `/ai/tts` (the comment in `src/app/api/v1/router.py`). Tests:
  `tests/api/v1/test_tts.py::TestGenerateSuccess::test_returns_a_sibling_relative_audio_url`,
  `tests/tts/test_waterfall.py::TestGenerateShortCircuit::test_a_repeat_generate_returns_the_absolute_bucket_url`.
- `TtsService.resolve_audio` answers the audio route in this order: join the generation already
  running for the hash; 404 when there is no recipe; 302 to the compressed object; join a finished
  generation that is still being read while its object isn't up yet; otherwise start a generation
  with this request as its first listener. The file name must be 64 lowercase hex characters with
  `.wav`, `.ogg` or `.mp3`, and the extension doesn't change which clip is served. A HEAD runs the
  same steps without the audio. Tests:
  `tests/tts/test_waterfall.py::TestRungOrder::test_an_in_flight_entry_wins_over_everything`,
  `tests/tts/test_waterfall.py::TestRungOrder::test_nothing_authorized_is_the_404_rung`,
  `tests/tts/test_waterfall.py::TestRungOrder::test_the_compressed_object_wins_over_a_new_generation`,
  `tests/tts/test_waterfall.py::TestDrainingSet::test_a_draining_entry_serves_attach_while_the_object_is_absent`,
  `tests/api/v1/test_tts_audio.py::TestNotFound::test_every_extension_fluent_api_relays_resolves_here`,
  `tests/api/v1/test_tts_audio.py::TestHeadProbe::test_warm_head_is_an_empty_redirect_without_provider_spend`.
- A process makes one generation per hash. Concurrent GETs and HEADs for a hash share one provider
  call, and each listener replays the audio from the first byte (`GenerationHeap` in
  `src/app/services/tts/generation.py`). **Exception:** nothing dedups across processes or
  instances. The worst case is paying twice, never a wrong clip (proposal §10.1, decision T26),
  and that is why the image runs one uvicorn worker. Tests:
  `tests/tts/test_waterfall.py::TestDedupAndAdmission::test_concurrent_first_listens_make_one_provider_call`,
  `tests/api/v1/test_tts_audio.py::TestHeadProbe::test_overlapping_get_and_head_share_one_generation`,
  `tests/tts/test_generation.py::TestReader::test_a_late_reader_gets_the_whole_buffer_from_the_start`.
- A new generation has to reserve a `TTS_MAX_CLIP_BYTES` slot out of `TTS_MAX_BUFFERED_BYTES`, 16
  slots by default. A request that can't get one within `TTS_ADMISSION_WAIT_SECONDS` gets a 503
  `TTS_BUSY` with `Retry-After` before any audio, while joining a generation, a 302 and a 404 skip
  admission. Tests: `tests/tts/test_generation.py::TestAdmission::test_over_budget_is_a_503_with_retry_after`,
  `tests/tts/test_generation.py::TestAdmission::test_concurrent_admissions_never_exceed_the_budget`,
  `tests/api/v1/test_tts_audio.py::TestAdmission::test_attaching_to_an_existing_generation_bypasses_admission`,
  `tests/tts/test_waterfall.py::TestDedupAndAdmission::test_a_302_is_served_even_when_the_budget_is_full`.
- A generation that fails ends every listener's stream with an aborted connection, never a clean
  end, and is dropped without a retry on the server, so the next request starts over.
  `TTS_GENERATION_TIMEOUT_SECONDS` bounds the synthesis, and a clip that grows past
  `TTS_MAX_CLIP_BYTES` fails with `TTS_CLIP_TOO_LONG`. Tests:
  `tests/tts/test_generation.py::TestReader::test_failure_mid_read_aborts_instead_of_ending`,
  `tests/api/v1/test_tts_audio.py::TestProviderFailure::test_a_failed_generation_is_dropped_and_never_retried_server_side`,
  `tests/tts/test_waterfall.py::TestFailure::test_a_stream_over_the_per_clip_ceiling_aborts`,
  `tests/tts/test_waterfall.py::TestFailure::test_generation_timeout_closes_the_provider_stream`.
- After synthesis, the compression tail encodes the clip with ffmpeg, uploads it with a
  conditional PUT and writes the receipt. A failure there is logged and swallowed: the listeners
  already have the audio, and the recipe keeps the clip regenerable. Tests:
  `tests/tts/test_compression_tail.py::TestTheHappyPath::test_a_finished_clip_is_encoded_and_uploaded`,
  `tests/tts/test_compression_tail.py::TestFailuresNeverCostTheClip::test_a_failed_encode_leaves_the_clip_regenerable`,
  `tests/tts/test_compression_tail.py::TestFailuresNeverCostTheClip::test_a_failed_tail_does_not_fail_the_generation_task`.
  **Grandfathered:** nothing bounds how long the tail takes, so an encoder that hangs keeps its
  admission slot. No test covers it.
- Shutdown cancels every generation in flight before it stops the worker, through
  `peek_tts_service`, which never builds a service that wasn't used. Listeners abort and slots come
  back. There is no "finish, then exit", since the recipe lets the next process regenerate. Tests:
  `tests/test_lifespan.py::test_shutdown_cancels_the_process_tts_generations`,
  `tests/test_lifespan.py::test_shutdown_never_builds_a_tts_service_that_was_never_used`,
  `tests/tts/test_waterfall.py::TestShutdown::test_shutdown_aborts_a_live_listener_and_drops_the_entry`.
- Every TTS setting is optional, so a deployment without them still boots. Without the R2 settings
  or `TTS_HASH_SECRET`, both TTS routes answer 503 `TTS_STORAGE_NOT_CONFIGURED` and the rest of the
  app works. Without `TTS_PUBLIC_AUDIO_BASE_URL`, `generate` always gives the cold URL, and once a
  clip is compressed its audio route answers 503, so a verse only plays during its first listen.
  Without a Google key, each generation fails. Settings are read once, so a fix needs a restart.
  Tests: `tests/api/v1/test_tts.py::TestAuthAndConfiguration::test_unconfigured_storage_is_a_503_not_a_boot_failure`,
  `tests/tts/test_waterfall.py::TestRungOrder::test_a_missing_public_base_url_is_a_clean_503_not_a_none_url`,
  `tests/tts/test_gemini_provider.py::TestFailures::test_a_missing_api_key_fails_the_generation_not_the_boot`.

## Data ownership

- fluent-ai runs SQL only against its own `ai` schema: `ai.api_keys`, `ai.jobs` and
  `ai.alembic_version`. `scripts/bootstrap.py` gives the `ai_user` and `ai_migrator` roles nothing
  outside it, every model sets `{"schema": "ai"}`, and `src/app/db/migrations/env.py` ignores
  every other schema. No test covers it.
- Whatever fluent-api owns comes over HTTP from fluent-api. For a suggestion job that is the verse
  text, the translation memory and the heading context, from
  `POST /ai-suggestions/internal/context`, and fluent-api picks the memory. fluent-ai keeps no suggestions: it sends them to
  `POST /ai-suggestions/internal/results` and keeps only the job row.
  [api-data-dependencies.md](api-data-dependencies.md) lists the direct reads that were removed.
  Tests: `src/tests/worker/test_heading_processor.py::test_verse_job_keeps_existing_context_and_results_contract`,
  `src/tests/worker/test_heading_processor.py::test_heading_job_uses_full_context_and_pushes_only_heading`.

## Content protection

- Gemini gets only what a task needs. A verse suggestion sends the target language name, the
  translation memory fluent-api chose (source and human translation of up to 100 verses) and the
  source verses, with ids like `GEN_1_1`. A heading suggestion sends the source title, the whole
  pericope and the memory, with an instruction to treat all of it as data, never as instructions,
  and a heading job without a source title sends nothing. Speech sends the text, the model and the
  voice. No prompt carries a project name, a user or a Bible id, and the `lang_code` of a speech
  request never leaves. Code: `TranslationService` in `src/app/services/translation_service.py`
  and `GeminiTtsProvider` in `src/app/services/tts/gemini_provider.py`. Tests:
  `src/tests/test_heading_translation.py::test_heading_prompt_preserves_source_title_and_all_pericope_context`,
  `src/tests/worker/test_heading_processor.py::test_heading_without_source_title_completes_without_generation`,
  `tests/tts/test_gemini_provider.py::TestCallShape::test_the_request_matches_the_2x_interactions_schema`.
  No test covers the verse prompt.
- **Exception:** for speech, fluent-ai never learns which Bible a text comes from, and checks no
  licence. A speech request is text plus an optional voice, format and `lang_code`
  (`TtsGenerateRequest` in `src/app/schemas/tts.py`, which refuses other fields), and `licenceBar`
  in fluent-web is the one place that decides whether a Bible may be spoken (decision T6 in the
  source-tts proposal, and fluent-web's
  [Scripture text](https://github.com/eten-tech-foundation/fluent-web/blob/main/docs/domain-rules.md#scripture-text)
  rules). Test: `tests/api/v1/test_tts.py::TestValidation::test_an_unknown_field_is_a_client_bug`.
- What fluent-ai keeps: `ai.jobs` payloads hold ids and numbers, not text. R2 keeps each speech
  clip's recipe, text included, and its audio for good, plus a receipt without text, and none of
  them names a user. The repeated word check keeps nothing. Tests:
  `src/tests/test_suggestions_service.py::test_heading_jobs_keep_separate_dedup_identity_and_persist_metadata`,
  `tests/tts/test_recipe.py::TestSidecarRoundTrip::test_sidecar_has_no_timestamp_or_user_identity`,
  `tests/tts/test_service.py::TestReceipt::test_receipt_contains_no_text_and_no_user_identity`.
- Logs carry ids, counts, lengths and codes, never Bible text, prompts, model output or keys. The
  speech service logs the clip's hash, text length and format, the repeated word route logs the
  language code and verse count, and `SensitiveDataFilter` (`src/app/logging/filters.py`) redacts
  structured fields with names like `api_key` or `token`. Tests:
  `tests/test_logging.py::TestSensitiveDataRedaction::test_sensitive_data_filter_scrubs_record`,
  `tests/tts/test_gemini_provider.py::TestFailures::test_the_spoken_text_never_appears_in_a_failure`.
  No test reads the log output. **Grandfathered:** validation errors quote the values that failed.
  The handler for a 422 in `src/app/errors/handlers.py` logs them, and a suggestion job that fails
  on bad context or a bad model answer logs them and keeps them in `ai.jobs.error_message`.
  Gemini's error text is also logged as it comes.

## Greek Room

The repeated word check wraps the `greekroom` package (`greekroom>=0.0.20` in `pyproject.toml`).
How it was designed is in [docs/features/greek-room-integration/](features/greek-room-integration/);
these are the decisions the code still holds.

- fluent-api calls `POST /tools/greek-room/repeated-words` at the service root:
  `src/app/api/v1/router.py` mounts the router under `/tools/greek-room`, and `src/app/main.py`
  includes the v1 router without a prefix. fluent-api builds the URL from `FLUENT_AI_URL` and
  `FLUENT_AI_API_PREFIX`, which is empty, so moving the routes under a prefix means changing that
  variable in the same release. Test:
  `tests/api/v1/test_greek_room.py::TestRepeatedWordsEndpoint::test_happy_path_real_greek_room`.
- Any valid key may run the check. It needs no `admin` permission: `check_repeated_words` in
  `src/app/api/v1/endpoints/greek_room.py` depends on `require_api_key` only. Tests:
  `tests/api/v1/test_greek_room.py::TestRepeatedWordsEndpoint::test_missing_api_key_returns_401`,
  and the happy path test calls it with a key that has no permissions.
- The check runs during the request and answers 200 with the `ToolJobResponse` envelope from
  `src/app/schemas/tool_job.py`. `status` is always `completed`, `error` is null, `tool` is
  `greek_room.repeated_words` (`RepeatedWordsService.name`), and `job_id` is a new UUID that is
  never stored, so there is nothing to poll. `JobStatus` also has `queued`, `running` and
  `cancelled`, which nothing sends yet. Test:
  `tests/api/v1/test_greek_room.py::TestRepeatedWordsEndpoint::test_happy_path_real_greek_room`.
  **Exception:** TTS answers `{audio_url}` without the envelope, because the audio arrives later
  over its own streaming request and fluent-api's shared client would drop `audio_url` (the module
  docstring of `src/app/api/v1/endpoints/tts.py`).
- A failure inside the `greekroom` call is a 502 `TOOL_EXECUTION_ERROR` with `details.tool`, never
  a `failed` envelope: `RepeatedWordsService.execute` in
  `src/app/services/greek_room/repeated_words.py` wraps `check_mcp` in `ToolExecutionException`.
  An error outside that call, while building the request or the result, is a 500. Test:
  `tests/api/v1/test_greek_room.py::TestRepeatedWordsEndpoint::test_tool_failure_returns_502` pins
  the 502 body, but its stub raises the exception itself, so no test covers the wrapping.
- The wire format is snake_case and fixed: the request and result models in
  `src/app/schemas/greek_room.py`, with `provider` set to `GreekRoom` and `check` to
  `RepeatedWords`. `greekroom`'s JSON-RPC request and its hyphenated keys stay inside
  `src/app/services/greek_room/repeated_words.py`. fluent-api checks the result against its own
  copy of the schema, so renaming or dropping a field breaks the check there. Test:
  `tests/api/v1/test_greek_room.py::TestRepeatedWordsEndpoint::test_happy_path_real_greek_room`
  checks the summary and each finding's `snt_id`, `legitimate` and `severity`. No test covers
  `repeated_word`, `surf` or `start_position`.
- What counts as a finding comes from `greekroom`, and the happy path test runs the real library:
  the same word twice in a row, ignoring case, with only spaces or punctuation between them, so
  `bye-bye` counts and a word said three times gives two findings. A pair listed for the request's
  exact `lang_code` in `greekroom`'s `legitimate_duplicates.jsonl` is `legitimate` with severity
  0.1, and any other pair gets 0.5. A `greekroom` upgrade that changes the data or the matching
  fails that test on purpose. Test:
  `tests/api/v1/test_greek_room.py::TestRepeatedWordsEndpoint::test_happy_path_real_greek_room`
  ("In in" in GEN 1:1 is suspicious, "Truly, truly" in JHN 3:3 is legitimate).
  **Grandfathered:** a verse whose text contains a line break gets no findings at all, because
  `greekroom` matches within one line. The service should send line breaks as spaces. No test
  covers it.
- `start_position` and `surf` should point at the repeated pair in the verse text as sent. Today
  `start_position` counts code points. **Grandfathered:** fluent-web slices the verse with it as
  UTF-16 units, so its highlight is off after a character outside the Basic Multilingual Plane,
  and a character that lowercases to two code points (such as `İ`) shifts both values. The
  contract should name one unit. No test covers it.
- The service is built once per process, in the lifespan, and endpoints get it through
  `get_repeated_words_service` in `src/app/dependencies.py`, which tests override. Building it
  only looks up the data file paths, and `greekroom` reads the files on every request. The check
  itself runs in a worker thread (`asyncio.to_thread`), off the event loop. Tests:
  `tests/api/v1/test_greek_room.py::TestRepeatedWordsEndpoint::test_happy_path_real_greek_room`
  uses the lifespan instance, and `test_tool_failure_returns_502` the override. No test covers the
  thread. **Grandfathered:** when the bundled data file is missing, the service still starts, and
  every pair comes back suspicious instead of the service failing at startup, as the lifespan
  comment in `src/app/main.py` intends. No test covers it.
