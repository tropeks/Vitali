# Imaging / PACS (DICOM) — Orthanc + OHIF

Vitali's imaging module tracks DICOM studies (`apps.imaging.DicomStudy`, one row
per `StudyInstanceUID`) and resolves pixel data through an **Orthanc** PACS with
the **OHIF** viewer plugin.

## Architecture

```
order/encounter ──> DicomStudy (tenant schema, pre-created, no orthanc_study_id)
                         ▲
                         │  (4) backfill orthanc_study_id + counts
                         │
Orthanc PACS  ──(1)──> /changes (PACS-wide feed)
   │  StableStudy        │
   │                  (2) poll cursor (Celery beat, every 3 min)
   └──(3)──> /studies/{id} + /studies/{id}/statistics
                         │
OHIF viewer (same-origin) <── viewer URL uses StudyInstanceUID
```

- **Orthanc** is deployed alongside Vitali and serves the **OHIF** plugin
  same-origin under the white-label route `/visualizador/`. The viewer URL for a study is:

  ```
  /visualizador/viewer?StudyInstanceUIDs=<StudyInstanceUID>
  ```

  Note the viewer keys off `StudyInstanceUID` (the DICOM identity), not the
  Orthanc resource id. `orthanc_study_id` is stored on the row as the proof the
  study has landed in the PACS (`DicomStudy.has_pixel_data`) and as the handle
  for any Orthanc-side REST calls.

## Ingestion flow (poll + match, **never create**)

1. The order / encounter flow pre-creates a `DicomStudy` row in the **tenant
   schema** with the known `study_instance_uid` and/or `accession_number`. At
   this point `orthanc_study_id` is empty.
2. A Celery beat task (`imaging.sync_orthanc_studies`, every 3 minutes) polls
   Orthanc's PACS-wide `/changes` feed from a stored cursor.
3. For every `StableStudy` change it fetches `/studies/{id}` (for
   `StudyInstanceUID` + `AccessionNumber`) and `/studies/{id}/statistics` (for
   accurate series/instance counts).
4. It then iterates **tenant schemas** and, in each, looks for a matching
   `DicomStudy` — by `study_instance_uid` first, falling back to
   `accession_number`. On a match it backfills `orthanc_study_id` and the
   series/instance counts (`save(update_fields=...)`). The cursor advances to
   the feed's `Last`.

Studies with **no matching `DicomStudy` in any tenant are logged and skipped** —
the task never auto-creates rows.

### Why match, not create (multi-tenant)

Orthanc's `/changes` feed is **global** (one PACS shared across all tenants).
A stray study landing in Orthanc carries no Vitali tenant identity, so we cannot
safely decide which schema it belongs to. Auto-creating would either guess wrong
or leak a study across tenant boundaries. Instead, the order flow owns row
creation inside the correct tenant; ingestion only **backfills** the PACS handle
onto rows that already exist.

### Idempotency & resilience

- The run is idempotent: re-running with the same cursor processes nothing new
  and never overwrites an already-correct `orthanc_study_id`.
- The task is a **no-op when `ORTHANC_URL` is empty** (feature inert).
- A transient Orthanc outage is logged and swallowed; the cursor is not
  advanced past unprocessed changes, so the next beat tick retries.

## Cursor storage

The `/changes` cursor is **PACS-wide / global**, but `apps.imaging` lives in
`TENANT_APPS` (schema-per-tenant) and has no public-schema table to hold a
singleton. Rather than introduce a new `SHARED_APPS` model + shared-schema
migration, the cursor is persisted in the **Django cache (Redis)** under the
fixed key `imaging:orthanc:last_change_seq`. Redis is already the cache backend,
the value survives restarts at the poll cadence we need, and there is exactly
one global cursor — matching the global nature of the feed.

## Backfill fallbacks

- **Manual PATCH** `PATCH /api/v1/imaging/studies/{id}/orthanc/` — set the
  Orthanc id (and counts) by hand. Kept as a fallback / for clinics without the
  poller.
- **On-demand trigger** `POST /api/v1/imaging/orthanc/sync/` — platform-admin
  only; runs one ingestion pass immediately and returns the summary
  (`{scanned, matched, skipped}`). Returns `200` with `inert: true` when
  `ORTHANC_URL` is unset.

## Settings (operator / trusted config)

| Setting | Default | Purpose |
|---------|---------|---------|
| `ORTHANC_URL` | `""` | Orthanc base URL. **Empty disables the feature.** |
| `ORTHANC_USERNAME` | `""` | Basic-auth user (blank → no auth header). |
| `ORTHANC_PASSWORD` | `""` | Basic-auth password. |
| `ORTHANC_HTTP_TIMEOUT` | `10` | Per-request timeout (seconds). |

These are **operator configuration, not user input**. The egress target
(`ORTHANC_URL`) is set by the deployer, so SSRF-style concerns about where the
poller connects are an operator/deploy responsibility (trusted config), not a
user-controlled request surface. The client performs read-only `GET`s only.
