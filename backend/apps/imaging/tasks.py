# mypy: ignore-errors
"""
Imaging Celery tasks — Orthanc → Vitali study ingestion (E-012).

A single periodic task polls the Orthanc PACS-wide ``/changes`` feed and
backfills matching tenant ``DicomStudy`` rows. It is a no-op when
``ORTHANC_URL`` is empty (feature inert) and swallows transient Orthanc
outages so the worker keeps running and simply retries on the next beat tick.
"""

import logging

from celery import shared_task
from django.conf import settings

from .services.orthanc_client import OrthancError
from .services.orthanc_sync import sync_orthanc_studies

logger = logging.getLogger(__name__)


@shared_task(name="imaging.sync_orthanc_studies")
def sync_orthanc_studies_task():
    """Poll Orthanc once and backfill matching DicomStudy rows.

    Returns the per-run summary dict (also useful for the on-demand endpoint).
    No-ops when ORTHANC_URL is unset. Transient Orthanc errors are logged and
    swallowed (retried on the next scheduled tick).
    """
    base = {
        "scanned": 0,
        "matched": 0,
        "skipped": 0,
        "ambiguous_skipped": 0,
        "error_skipped": 0,
        "lock_skipped": False,
    }

    if not getattr(settings, "ORTHANC_URL", ""):
        logger.debug("imaging.sync_orthanc_studies: ORTHANC_URL empty — feature inert")
        return {**base, "inert": True}

    try:
        summary = sync_orthanc_studies()
    except OrthancError:
        logger.warning(
            "imaging.sync_orthanc_studies: Orthanc unreachable this tick — will retry",
            exc_info=True,
        )
        return {**base, "error": "orthanc_unreachable"}

    logger.info("imaging.sync_orthanc_studies: %s", summary)
    return summary
