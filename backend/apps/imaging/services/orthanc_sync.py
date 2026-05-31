"""
Orthanc → Vitali study ingestion (E-012).

Polls the PACS-wide Orthanc ``/changes`` feed and, for every ``StableStudy``
change, backfills the matching tenant ``DicomStudy.orthanc_study_id`` (plus the
series/instance counts) so the OHIF viewer can resolve pixel data.

Design notes
------------
* **Match, never create.** A study with no pre-registered ``DicomStudy`` in any
  tenant is logged and skipped — we never auto-create rows, because the change
  feed is global (PACS-wide) and we cannot know which tenant a stray study
  belongs to. ``DicomStudy`` rows are pre-created by the order flow.
* **Cursor storage = Django cache (Redis).** The Orthanc ``/changes`` cursor is
  global, but ``apps.imaging`` lives in TENANT_APPS (schema-per-tenant), so it
  has no public-schema table to hold a singleton. Rather than add a new
  SHARED_APPS model + shared migration, we persist the cursor under a fixed
  cache key (Redis is already the cache backend). Simple, global, survives
  restarts for the poll cadence we need.
* **Idempotent.** Re-running with the same cursor advances nothing and writes
  nothing new (already-set ``orthanc_study_id`` values are left untouched).
"""

from __future__ import annotations

import logging

from django.core.cache import cache

from apps.core.tenancy import for_each_tenant_schema

from .orthanc_client import OrthancClient

logger = logging.getLogger(__name__)

# Fixed global cache key for the Orthanc /changes cursor (PACS-wide).
CURSOR_CACHE_KEY = "imaging:orthanc:last_change_seq"
# Cursor must not expire — pin it effectively forever.
CURSOR_CACHE_TTL = None

CHANGES_PAGE_LIMIT = 100


def _read_cursor() -> int:
    return int(cache.get(CURSOR_CACHE_KEY) or 0)


def _write_cursor(value: int) -> None:
    cache.set(CURSOR_CACHE_KEY, int(value), CURSOR_CACHE_TTL)


def _apply_study_to_tenants(
    *,
    orthanc_id: str,
    study_uid: str,
    accession: str,
    n_series: int,
    n_instances: int,
) -> bool:
    """Find the matching ``DicomStudy`` across tenant schemas and backfill it.

    Returns True if a row was matched in any tenant (StudyInstanceUID is
    globally unique in DICOM, so at most one tenant should match).
    """
    from apps.imaging.models import DicomStudy

    def _match_in_schema(schema_name: str) -> bool:
        study = None
        if study_uid:
            study = DicomStudy.objects.filter(study_instance_uid=study_uid).first()
        if study is None and accession:
            study = DicomStudy.objects.filter(accession_number=accession).first()
        if study is None:
            return False

        fields: list[str] = []
        if study.orthanc_study_id != orthanc_id:
            study.orthanc_study_id = orthanc_id
            fields.append("orthanc_study_id")
        if n_series and study.number_of_series != n_series:
            study.number_of_series = n_series
            fields.append("number_of_series")
        if n_instances and study.number_of_instances != n_instances:
            study.number_of_instances = n_instances
            fields.append("number_of_instances")
        if fields:
            study.save(update_fields=fields)
            logger.info(
                "orthanc_sync: matched study uid=%s acc=%s → tenant=%s orthanc_id=%s (%s)",
                study_uid,
                accession,
                schema_name,
                orthanc_id,
                ",".join(fields),
            )
        return True

    results = for_each_tenant_schema(
        _match_in_schema, logger=logger, operation="orthanc_sync match"
    )
    return any(results)


def sync_orthanc_studies(client: OrthancClient | None = None) -> dict[str, int]:
    """Run one ingestion pass. Returns a summary dict.

    Reads changes since the stored cursor, processes ``StableStudy`` changes,
    backfills matching tenant ``DicomStudy`` rows, and advances the cursor.
    Raises ``OrthancError`` on transport failure (caller decides to retry).
    """
    client = client or OrthancClient()
    summary = {"scanned": 0, "matched": 0, "skipped": 0}

    start = _read_cursor()
    since = start
    last = start

    while True:
        page = client.get_changes(since, limit=CHANGES_PAGE_LIMIT)
        changes = page.get("Changes") or []
        for change in changes:
            last = change.get("Seq", last)
            if change.get("ChangeType") != "StableStudy":
                continue
            orthanc_id = change.get("ID")
            if not orthanc_id:
                continue
            summary["scanned"] += 1
            study = client.get_study(orthanc_id)
            stats = client.get_study_statistics(orthanc_id)
            study_uid = client.study_instance_uid(study)
            accession = client.accession_number(study)
            n_series = client.series_count(study, stats)
            n_instances = client.instance_count(study, stats)
            matched = _apply_study_to_tenants(
                orthanc_id=orthanc_id,
                study_uid=study_uid,
                accession=accession,
                n_series=n_series,
                n_instances=n_instances,
            )
            if matched:
                summary["matched"] += 1
            else:
                summary["skipped"] += 1
                logger.info(
                    "orthanc_sync: no DicomStudy matches orthanc_id=%s uid=%s acc=%s — skipping",
                    orthanc_id,
                    study_uid,
                    accession,
                )

        # Advance to the page's Last so the next page (or next tick) resumes.
        page_last = page.get("Last", last)
        last = page_last
        if page.get("Done", True) or page_last <= since:
            # Done, or the cursor failed to advance — stop to avoid a tight loop.
            since = page_last
            break
        since = page_last

    if last != start:
        _write_cursor(last)
    return summary
