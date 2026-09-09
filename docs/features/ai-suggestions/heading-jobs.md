# Pericope heading suggestions

The existing `POST /suggestions` batch accepts an optional `pericopeNumber`
(nonblank, at most 100 characters). Its presence selects a heading-only job.
`projectUnitId`, `bibleId`, `bookCode`, `chapterNumber`, `verseStart`, and
`verseEnd` remain required. `pericopeSetId` is optional on this request; the API
includes it when enqueueing headings to bind the job to the selected source set.

Heading jobs have a separate deduplication key based on the complete request,
including the verse range, pericope number, and source set. Requests without a
pericope number keep the existing verse job key and HTTP payloads.

The worker forwards the heading identity to
`POST /ai-suggestions/internal/context`. In addition to `targetLanguageName`,
`contextVerses`, and the entire pericope's `sourceVerses`, the API returns:

```json
{
  "sectionHeading": {
    "pericopeNumber": "14.2",
    "pericopeSetId": 7,
    "bibleTextId": 42,
    "sourceTitle": "Jesus feeds the crowd"
  }
}
```

The worker checks that the pericope and supplied set match the job and that the
Bible text ID belongs to the first source verse. A missing/null section heading
or missing/null/blank source title completes the job without calling Gemini or
pushing a result. Invalid identity or malformed metadata fails without retries.

`TranslationService.translate_heading` requests one translated heading in
structured JSON. It uses the source title's intent, all source verses, and the
translation memory. Generated text is trimmed and must contain 1–300 UTF-16 code
units, on a single line, with no USFM backslashes or control characters. Invalid
model output uses the existing bounded job retries, as do transient API failures.

The result is sent to `POST /ai-suggestions/internal/results`:

```json
{
  "items": [],
  "heading": {
    "projectUnitId": 1,
    "bibleTextId": 42,
    "pericopeNumber": "14.2",
    "pericopeSetId": 7,
    "suggestedText": "Jesús alimenta a la multitud",
    "modelInfo": "configured-google-ai-model"
  }
}
```

The API validates the source set again when saving. Heading jobs never produce
verse translations; ordinary verse jobs continue to send only `items`.
