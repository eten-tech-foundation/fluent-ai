# ai.jobs health: stats endpoint and failure alerting — Design

Issue [#85](https://github.com/eten-tech-foundation/fluent-ai/issues/85).
Related: [#84](https://github.com/eten-tech-foundation/fluent-ai/issues/84)
made individual failures diagnosable and re-triggerable; this is about
*detecting* them.

## Problem

In QA the suggestion pipeline failed 100% of jobs in two multi-day windows
(context-call 401s Sep 15–Oct 19; Gemini `402 RESOURCE_EXHAUSTED` Oct 20–22)
and nobody noticed until a user reported it. fluent-ai's logs only reach
container stdout, and there was nothing an operator could poll.

## A. `GET /jobs/stats` (shipped)

Authenticated with the usual `X-API-Key`. Reads `ai.jobs` on every call and
returns a gauge — current state, never events — so any number of pollers can
call it without double counting. No `payload` field appears anywhere.

```bash
curl -s "$FLUENT_AI_URL/jobs/stats?window_hours=24" -H "X-API-Key: $KEY"
```

```json
{
  "window_hours": 24,
  "lifetime": {"queued": 0, "processing": 0, "completed": 5120, "failed": 312},
  "recent":   {"queued": 0, "processing": 0, "completed": 0,    "failed": 41},
  "oldest_queued_at": null,
  "oldest_processing_at": null,
  "oldest_failed_at": "2026-09-15T08:02:11+00:00",
  "latest_failure": {
    "failed_at": "2026-10-22T09:14:03+00:00",
    "task_type": "ai_suggestion",
    "error_message": "Permanently failed after 3 retries: ... 402 RESOURCE_EXHAUSTED ..."
  }
}
```

- Every timestamp is `updated_at`, i.e. **when the row entered its current
  status**. `recent` counts rows that entered their current status within
  `window_hours` (1–720, default 24). A completed job only stays in
  `recent.completed` while it is newer than the window, so `recent.failed > 0`
  with `recent.completed == 0` is the total-outage signature.
- `oldest_queued_at` / `oldest_processing_at` expose a dead or stuck worker
  even when nothing has failed. `processing` rows older than 15 minutes are
  reclaimed by the worker, so an old `oldest_processing_at` means no worker is
  polling.
- `oldest_failed_at` is the oldest failure that has not been re-triggered (a
  re-trigger resets a failed row to `queued`, see #84).
- `latest_failure.error_message` goes through `scrub_text`
  (`app/logging/filters.py`), which redacts credential-looking
  `key=` / `token:` / `Authorization: Bearer …` values. The worker already
  caps the column at 500 characters.
- Lifetime counts include everything ever written to the table; there is no
  retention on `ai.jobs` today.

## B. Alerting recommendation

### Decision

1. **Now, configuration only (QA, then prod):** route the App Service
   container's stdout to Log Analytics with an App Service **diagnostic
   setting** (`AppServiceConsoleLogs`), and add a **scheduled-query alert
   rule** next to `fluent-server-qa-worker-heartbeat-missing` in `Fluent-QA`.
   This reuses the JSON lines fluent-ai already prints (QA and prod deploy with
   `ENVIRONMENT=production`, which selects `JsonFormatter`), so it needs no code
   change and no new dependency.
2. **Follow-up ticket, small code change:** have the worker log the
   `get_job_stats` result as a structured `ai_jobs_stats` event once per poll
   cycle. This is exactly fluent-api's `worker_dlq_depth` pattern: the alert
   reads the latest gauge sample, and a separate missing-signal rule fires when
   the worker stops reporting. Then switch the rule from text matching to that
   event.

### Rule for step 1 (draft — validate in the Logs blade before saving)

The worker writes one `ERROR` line per terminal failure:
`Job <id> permanently failed (non-retryable).` or
`Job <id> permanently failed after 3 retries.` Both QA outage windows went
through this path.

```kusto
AppServiceConsoleLogs
| where TimeGenerated > ago(30m)
| extend log = parse_json(ResultDescription)
| where tostring(log.level) == "ERROR"
| where tostring(log.message) has "permanently failed"
| summarize failures = count()
| where failures >= 3
```

Evaluate every 5 minutes over a 30-minute window, and fire when a row is
returned. The threshold is deliberately crude: the failure mode to catch is
total, and a healthy QA rarely fails three jobs in 30 minutes. Bind the rule to
the environment's approved action group; choosing one is the environment
owner's call.

### Why not the alternatives

- **Azure Monitor OpenTelemetry exporter into Application Insights.** This
  adds a dependency and startup wiring to get `customDimensions`. Today's log
  calls are f-strings with no structured fields, so it would buy nothing a
  diagnostic setting doesn't. The step 2 event is JSON on stdout, which KQL
  reads with `parse_json(ResultDescription)` without any exporter.
- **External monitor polling `/jobs/stats` as the primary alert.** As far as
  this repo knows, nothing in the estate polls JSON and applies a threshold.
  Application Insights availability tests can only match a status code or a
  substring, and the monitor would need a provisioned API key. The endpoint is
  still the right tool for on-call triage, and for any poller added later
  (alert when `recent.failed` grows while `recent.completed` stays 0, or
  `oldest_queued_at` is older than ~15 minutes).

### Where it lives and the `scribe-server-dev` question

A diagnostic setting targets a **Log Analytics workspace**, not an Application
Insights component. So fluent-ai does not need to join `scribe-server-dev`, the
component that already, confusingly, serves `fluent-server-qa`. Send fluent-ai's
console logs to the workspace that backs the existing `Fluent-QA` rules, so
the new rule sits beside the heartbeat rule. If an Application Insights
component is ever needed (for example for request telemetry), create one named
for fluent-ai on the same workspace rather than reusing `scribe-server-dev`.
Prod repeats the same diagnostic setting and rule in its own resource group.

### Known gaps in step 1 (closed by step 2)

- Two terminal paths set `status = 'failed'` without logging "permanently
  failed": `No source verses found …` and `No valid translations to save …`.
  A log rule cannot see them; the stats gauge can.
- A dead worker logs nothing, so a log-count rule stays silent. Step 2's
  missing-signal rule (no `ai_jobs_stats` sample in 10 minutes) covers this.
- Text matching depends on the wording of the worker's log line. Step 2 makes
  it a field match.

### To verify before configuring (not checkable from this repo)

- That `scribe-server-dev` is workspace-based, and which workspace the
  `Fluent-QA` heartbeat rule queries.
- That the fluent-ai App Service plan offers the `AppServiceConsoleLogs`
  category under Diagnostic settings.
- Ingestion cost: fluent-ai logs one line per request plus worker activity,
  which should be small next to fluent-api.
