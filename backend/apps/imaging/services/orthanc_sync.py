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
        "identity_mismatch_skipped": 0,
        "error_skipped": 0,
        "lock_skipped": False,
    }


def _identity_matches(study, *, patient_id: str, patient_id_issuer: str) -> bool:
    """Fail closed unless Orthanc's patient identity equals the registered pair."""
    return bool(
        patient_id
        and study.dicom_patient_id
        and patient_id == study.dicom_patient_id
        and patient_id_issuer == study.dicom_patient_id_issuer
    )


def _backfill_study(study, *, orthanc_id, n_series, n_instances):
    """Apply orthanc id + counts to a matched ``DicomStudy`` row, saving deltas.

    Callers must validate UID, accession and patient identity before this write.
    """
    fields: list[str] = []
    if study.orthanc_study_id != orthanc_id:
        study.orthanc_study_id = orthanc_id
        fields.append("orthanc_study_id")
    if not study.dicom_identity_verified:
        study.dicom_identity_verified = True
        fields.append("dicom_identity_verified")
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
    patient_id: str,
    patient_id_issuer: str,
    n_series: int,
    n_instances: int,
    expected_candidate: tuple[str, str] | None = None,
) -> str:
    """Link an Orthanc study to EXACTLY one tenant ``DicomStudy``.

    UID/accession select a candidate, but only an exact DICOM PatientID + Issuer
    match authorizes writing. Any duplicate candidate, including inside one
    tenant, is ambiguous and results in no write.
    """
    from apps.imaging.models import DicomStudy

    candidates: list[tuple[str, str]] = []

    def _find(field: str, value: str, operation: str) -> list[tuple[str, str]]:
        def _scan(schema_name: str):
            try:
                ids = list(DicomStudy.objects.filter(**{field: value}).values_list("id", flat=True))
            except DatabaseError:
                logger.exception("orthanc_sync: DB error in %s tenant=%s", operation, schema_name)
                return []
            return [(schema_name, str(pk)) for pk in ids]

        found = for_each_tenant_schema(_scan, logger=logger, operation=operation)
        return [candidate for tenant_rows in found if tenant_rows for candidate in tenant_rows]

    if study_uid:
        candidates = _find("study_instance_uid", study_uid, "orthanc_sync uid scan")
    if not candidates and accession:
        candidates = _find("accession_number", accession, "orthanc_sync accession scan")
    if not candidates:
        return "skipped"
    if len(candidates) != 1:
        logger.warning(
            "orthanc_sync: AMBIGUOUS uid=%s accession=%s orthanc_id=%s candidates=%s",
            study_uid,
            accession,
            orthanc_id,
            candidates,
        )
        return "ambiguous"
    if expected_candidate is not None and candidates[0] != expected_candidate:
        logger.warning(
            "orthanc_sync: manual target mismatch expected=%s resolved=%s orthanc_id=%s",
            expected_candidate,
            candidates[0],
            orthanc_id,
        )
        return "identity_mismatch"
    target, study_pk = candidates[0]
    try:
        with schema_context(target):
            study = DicomStudy.objects.filter(pk=study_pk).first()
            if study is None:
                return "skipped"
            if study.study_instance_uid != study_uid:
                return "identity_mismatch"
            if study.accession_number and study.accession_number != accession:
                return "identity_mismatch"
            if not _identity_matches(
                study, patient_id=patient_id, patient_id_issuer=patient_id_issuer
            ):
                logger.warning(
                    "orthanc_sync: PATIENT IDENTITY MISMATCH tenant=%s study=%s orthanc_id=%s",
                    target,
                    study.pk,
                    orthanc_id,
                )
                return "identity_mismatch"
            changed = _backfill_study(
                study,
                orthanc_id=orthanc_id,
                n_series=n_series,
                n_instances=n_instances,
            )
    except DatabaseError:
        logger.exception(
            "orthanc_sync: DB error saving accession match in tenant=%s (skipped)",
            target,
        )
        return "skipped"
    logger.info(
        "orthanc_sync: identity verified uid=%s → tenant=%s orthanc_id=%s (%s)",
        study_uid,
        target,
        orthanc_id,
        ",".join(changed) or "no-op",
    )
    return "matched"


def ingest_one_study(orthanc_id: str, *, client: OrthancClient | None = None) -> str:
    """Fetch ONE Orthanc study and backfill the matching tenant ``DicomStudy``.

    The *push* counterpart of the cursor-driven poller: the Orthanc webhook
    (``OnStableStudy`` Lua hook) calls this with the study's Orthanc id the
    moment it becomes stable, so ``orthanc_study_id`` is backfilled immediately
    instead of waiting for the next beat tick. The match/backfill rules are
    identical to the poller — it reuses :func:`_apply_study_to_tenants`, so a
    study with no pre-registered row is matched against ``DicomStudy`` rows that
    already exist (never auto-created, see module docstring).

    Returns the outcome: ``"matched"``, ``"skipped"`` or ``"ambiguous"``.
    Raises :class:`OrthancError` if the study cannot be fetched (the caller
    decides whether to surface a 502 so the PACS can retry).
    """
    client = client or OrthancClient()
    study = client.get_study(orthanc_id)
    stats = client.get_study_statistics(orthanc_id)
    return _apply_study_to_tenants(
        orthanc_id=orthanc_id,
        study_uid=client.study_instance_uid(study),
        accession=client.accession_number(study),
        patient_id=client.patient_id(study),
        patient_id_issuer=client.issuer_of_patient_id(study),
        n_series=client.series_count(study, stats),
        n_instances=client.instance_count(study, stats),
    )


def verify_and_link_study(study_row, orthanc_id: str, *, client: OrthancClient | None = None) -> str:
    """Server-side verification used by the manual PATCH endpoint.

    This intentionally uses the same global uniqueness and patient-identity
    rules as webhook/poll ingestion; an authenticated operator cannot bypass
    PACS metadata by posting counts or identifiers asserted by the browser.
    """
    from django.db import connection

    client = client or OrthancClient()
    payload = client.get_study(orthanc_id)
    stats = client.get_study_statistics(orthanc_id)
    return _apply_study_to_tenants(
        orthanc_id=orthanc_id,
        study_uid=client.study_instance_uid(payload),
        accession=client.accession_number(payload),
        patient_id=client.patient_id(payload),
        patient_id_issuer=client.issuer_of_patient_id(payload),
        n_series=client.series_count(payload, stats),
        n_instances=client.instance_count(payload, stats),
        expected_candidate=(connection.schema_name, str(study_row.pk)),
    )


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
                patient_id = client.patient_id(study)
                patient_id_issuer = client.issuer_of_patient_id(study)
                n_series = client.series_count(study, stats)
                n_instances = client.instance_count(study, stats)

                outcome = _apply_study_to_tenants(
                    orthanc_id=orthanc_id,
                    study_uid=study_uid,
                    accession=accession,
                    patient_id=patient_id,
                    patient_id_issuer=patient_id_issuer,
                    n_series=n_series,
                    n_instances=n_instances,
                )
                if outcome == "matched":
                    summary["matched"] += 1
                elif outcome == "ambiguous":
                    summary["ambiguous_skipped"] += 1
                elif outcome == "identity_mismatch":
                    summary["identity_mismatch_skipped"] += 1
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
