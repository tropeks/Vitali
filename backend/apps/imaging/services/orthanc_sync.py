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
* **Match to EXACTLY one tenant — never fan a single study into many.**
  ``StudyInstanceUID`` is a globally unique DICOM identifier, so it is the
  authoritative key: the first tenant whose ``DicomStudy`` carries the UID wins
  and we stop scanning. ``AccessionNumber`` is NOT globally unique across
  clinics, so it is only a fallback used when no tenant matched by UID, and only
  when it resolves to a single tenant; an accession that collides across two or
  more tenants is ambiguous and we update NONE of them (a cross-tenant PHI leak
  otherwise). The accession fallback also never overwrites an already-set
  ``orthanc_study_id`` (the link was established by a stronger signal).
* **Cursor storage = Django cache (Redis).** The Orthanc ``/changes`` cursor is
  global, but ``apps.imaging`` lives in TENANT_APPS (schema-per-tenant), so it
  has no public-schema table to hold a singleton. Rather than add a new
  SHARED_APPS model + shared migration, we persist the cursor under a fixed
  cache key (Redis is already the cache backend). Simple, global, survives
  restarts for the poll cadence we need.
* **Resilient.** A single deleted/unfetchable study (404 / ``OrthancError`` on
  ``get_study``) or a single tenant DB error is logged and skipped without
  aborting the run, and the cursor still advances past it (the feed must never
  permanently stall on one poison-pill change). Only a hard failure to fetch
  ``/changes`` aborts — and then the cursor is simply left unadvanced.
* **Single-flight.** A non-blocking cache lock guards a run so the beat task and
  the manual trigger cannot race the cursor (lost-update). A stuck lock simply
  self-expires.
* **Idempotent.** Re-running with the same cursor advances nothing and writes
  nothing new (already-set ``orthanc_study_id`` values are left untouched).
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import DatabaseError
from django_tenants.utils import schema_context

from apps.core.tenancy import for_each_tenant_schema

from .orthanc_client import OrthancClient, OrthancError

logger = logging.getLogger(__name__)

# Fixed global cache key for the Orthanc /changes cursor (PACS-wide).
CURSOR_CACHE_KEY = "imaging:orthanc:last_change_seq"
# Cursor must not expire — pin it effectively forever.
CURSOR_CACHE_TTL = None

# Non-blocking single-flight lock so the beat task and the manual trigger never
# race the cursor. A stuck lock self-expires after the timeout.
SYNC_LOCK_KEY = "imaging:orthanc:sync:lock"
SYNC_LOCK_TTL = 300  # seconds

CHANGES_PAGE_LIMIT = 100


def _read_cursor() -> int:
    return int(cache.get(CURSOR_CACHE_KEY) or 0)


def _write_cursor(value: int) -> None:
    cache.set(CURSOR_CACHE_KEY, int(value), CURSOR_CACHE_TTL)


def _empty_summary() -> dict:
    return {
        "scanned": 0,
        "matched": 0,
        "skipped": 0,
        "ambiguous_skipped": 0,
        "error_skipped": 0,
        "lock_skipped": False,
    }


def _backfill_study(study, *, orthanc_id, n_series, n_instances, allow_link_overwrite):
    """Apply orthanc id + counts to a matched ``DicomStudy`` row, saving deltas.

    ``allow_link_overwrite`` gates writing a *different* ``orthanc_study_id`` over
    one that is already set: UID matches are authoritative (True); the weak
    accession fallback must never repoint an existing link (False). When the id
    already equals the target it is a no-op regardless.
    """
    fields: list[str] = []
    if study.orthanc_study_id != orthanc_id:
        if study.orthanc_study_id and not allow_link_overwrite:
            # Accession fallback must not repoint an already-linked study.
            pass
        else:
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
    return fields


def _apply_study_to_tenants(
    *,
    orthanc_id: str,
    study_uid: str,
    accession: str,
    n_series: int,
    n_instances: int,
) -> str:
    """Link an Orthanc study to EXACTLY one tenant ``DicomStudy``.

    Algorithm (never writes to more than one tenant):

    1. **UID pass (authoritative).** Scan tenant schemas for a ``DicomStudy``
       with ``study_instance_uid == study_uid``. The FIRST match wins: backfill
       it and STOP scanning (short-circuit). UID matches may overwrite an
       existing ``orthanc_study_id`` (still authoritative). Returns ``"matched"``.

    2. **Accession fallback** (only if NO tenant matched by UID). Collect every
       tenant whose ``DicomStudy`` has ``accession_number == accession``:
         * 0 tenants  → ``"skipped"`` (no match anywhere).
         * 1 tenant   → backfill it, but NEVER overwrite an existing
           ``orthanc_study_id`` (accession is a weak signal). Returns ``"matched"``.
         * 2+ tenants → ambiguous accession collision across clinics: update
           NONE of them, log a warning, return ``"ambiguous"``.

    Per-tenant DB errors are isolated (logged + skipped) so one bad tenant never
    aborts the run. Returns one of ``"matched"``, ``"skipped"``, ``"ambiguous"``.
    """
    from apps.imaging.models import DicomStudy

    # ── Pass 1: UID (globally unique → FIRST match is authoritative, then STOP).
    # We must never write to more than one tenant. for_each_tenant_schema has no
    # early-exit, so the callback latches on the first hit and no-ops the rest:
    # even on a (data-error) UID collision across clinics, only ONE tenant is
    # written. A list cell carries the latch across the closure calls.
    if study_uid:
        uid_hit: list[str] = []

        def _match_uid(schema_name: str):
            if uid_hit:
                # Already linked the first matching tenant — short-circuit the rest.
                return None
            try:
                study = DicomStudy.objects.filter(study_instance_uid=study_uid).first()
            except DatabaseError:
                logger.exception(
                    "orthanc_sync: DB error matching uid=%s in tenant=%s (skipped)",
                    study_uid,
                    schema_name,
                )
                return None
            if study is None:
                return None
            try:
                changed = _backfill_study(
                    study,
                    orthanc_id=orthanc_id,
                    n_series=n_series,
                    n_instances=n_instances,
                    allow_link_overwrite=True,
                )
            except DatabaseError:
                logger.exception(
                    "orthanc_sync: DB error saving uid match in tenant=%s (skipped)",
                    schema_name,
                )
                return None
            uid_hit.append(schema_name)
            logger.info(
                "orthanc_sync: matched by uid=%s → tenant=%s orthanc_id=%s (%s)",
                study_uid,
                schema_name,
                orthanc_id,
                ",".join(changed) or "no-op",
            )
            return schema_name

        for_each_tenant_schema(_match_uid, logger=logger, operation="orthanc_sync uid match")
        if uid_hit:
            # First UID match is authoritative — exactly one tenant linked.
            return "matched"

    # ── Pass 2: accession fallback (only when no UID match anywhere). ──────────
    if not accession:
        return "skipped"

    def _find_accession(schema_name: str):
        try:
            study = DicomStudy.objects.filter(accession_number=accession).first()
        except DatabaseError:
            logger.exception(
                "orthanc_sync: DB error matching accession=%s in tenant=%s (skipped)",
                accession,
                schema_name,
            )
            return None
        return schema_name if study is not None else None

    found = for_each_tenant_schema(
        _find_accession, logger=logger, operation="orthanc_sync accession scan"
    )
    matched_schemas = [s for s in found if s is not None]

    if not matched_schemas:
        return "skipped"

    if len(matched_schemas) > 1:
        logger.warning(
            "orthanc_sync: AMBIGUOUS accession=%s for orthanc_id=%s matches "
            "multiple tenants %s — refusing to write any (cross-tenant collision)",
            accession,
            orthanc_id,
            matched_schemas,
        )
        return "ambiguous"

    # Exactly one tenant matched by accession — backfill it (never repoint a link).
    target = matched_schemas[0]
    try:
        with schema_context(target):
            study = DicomStudy.objects.filter(accession_number=accession).first()
            if study is None:
                # Row vanished between scan and apply — treat as no match.
                return "skipped"
            changed = _backfill_study(
                study,
                orthanc_id=orthanc_id,
                n_series=n_series,
                n_instances=n_instances,
                allow_link_overwrite=False,
            )
    except DatabaseError:
        logger.exception(
            "orthanc_sync: DB error saving accession match in tenant=%s (skipped)",
            target,
        )
        return "skipped"
    logger.info(
        "orthanc_sync: matched by accession=%s → tenant=%s orthanc_id=%s (%s)",
        accession,
        target,
        orthanc_id,
        ",".join(changed) or "no-op",
    )
    return "matched"


def sync_orthanc_studies(client: OrthancClient | None = None) -> dict:
    """Run one ingestion pass. Returns a summary dict.

    Reads changes since the stored cursor, processes ``StableStudy`` changes,
    backfills the single matching tenant ``DicomStudy`` row, and advances the
    cursor to the highest change actually processed (matched, skipped-no-match,
    skipped-ambiguous, and skipped-on-error all count as processed, so the feed
    always moves forward and is idempotent).

    Guarded by a non-blocking cache lock: if a run is already in flight the call
    returns early with ``lock_skipped=True`` and does NOT touch the cursor.

    A hard failure to fetch ``/changes`` raises ``OrthancError`` (caller decides
    to retry) and leaves the cursor unadvanced (nothing was processed). A single
    unfetchable/deleted study or a single-tenant DB error is logged and skipped.
    """
    summary = _empty_summary()

    # ── Single-flight lock (covers both the beat task and the manual trigger). ─
    if not cache.add(SYNC_LOCK_KEY, "1", SYNC_LOCK_TTL):
        logger.info("orthanc_sync: a sync run is already in flight — skipping (locked)")
        summary["lock_skipped"] = True
        return summary

    try:
        client = client or OrthancClient()

        start = _read_cursor()
        since = start
        # Highest Seq we have actually processed (advances even past poison pills).
        processed = start

        while True:
            # Hard failure to fetch /changes aborts the run (cursor unadvanced).
            page = client.get_changes(since, limit=CHANGES_PAGE_LIMIT)
            changes = page.get("Changes") or []
            for change in changes:
                seq = change.get("Seq")
                if change.get("ChangeType") != "StableStudy":
                    # Non-study changes are "processed" — let the cursor pass them.
                    if seq is not None:
                        processed = max(processed, seq)
                    continue
                orthanc_id = change.get("ID")
                if not orthanc_id:
                    if seq is not None:
                        processed = max(processed, seq)
                    continue

                summary["scanned"] += 1
                try:
                    study = client.get_study(orthanc_id)
                    stats = client.get_study_statistics(orthanc_id)
                except OrthancError:
                    # Poison pill: study deleted/unfetchable after the change was
                    # emitted. Log, count as error-skipped, advance past it.
                    logger.warning(
                        "orthanc_sync: failed to fetch orthanc_id=%s (seq=%s) — "
                        "skipping this change, run continues",
                        orthanc_id,
                        seq,
                        exc_info=True,
                    )
                    summary["error_skipped"] += 1
                    if seq is not None:
                        processed = max(processed, seq)
                    continue

                study_uid = client.study_instance_uid(study)
                accession = client.accession_number(study)
                n_series = client.series_count(study, stats)
                n_instances = client.instance_count(study, stats)

                outcome = _apply_study_to_tenants(
                    orthanc_id=orthanc_id,
                    study_uid=study_uid,
                    accession=accession,
                    n_series=n_series,
                    n_instances=n_instances,
                )
                if outcome == "matched":
                    summary["matched"] += 1
                elif outcome == "ambiguous":
                    summary["ambiguous_skipped"] += 1
                else:  # "skipped"
                    summary["skipped"] += 1
                    logger.info(
                        "orthanc_sync: no DicomStudy matches orthanc_id=%s uid=%s "
                        "acc=%s — skipping",
                        orthanc_id,
                        study_uid,
                        accession,
                    )

                if seq is not None:
                    processed = max(processed, seq)

            # Persist incrementally so progress survives a mid-run crash.
            if processed != start:
                _write_cursor(processed)

            page_last = page.get("Last", processed)
            if page.get("Done", True) or page_last <= since:
                # Done, or the cursor failed to advance — stop to avoid a tight loop.
                since = page_last
                break
            since = page_last

        return summary
    finally:
        cache.delete(SYNC_LOCK_KEY)
