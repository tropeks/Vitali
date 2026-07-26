"""C5-P2 — Imaging→consumption auto-wire (concession-side seam).

A DICOM study performed at a unit CONSUMES the mapped service's recipe. This
bridge lives concession-side so ``imaging`` stays independent: concession hooks
``imaging.DicomStudy``'s ``post_save`` and, ONLY when the tenant has the
``diagnostic_concession`` module active AND the study resolves to a
``(service, unit)`` pair, records an idempotent :class:`ExamConsumption`.

It NEVER raises into the study save — a consumption failure (e.g. insufficient
stock) must not block or roll back the exam. Idempotency is the existing
per-study key (``study:<pk>``), so a re-save never double-deducts.
"""

from __future__ import annotations

import logging

from django.db import connection
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def resolve_concession_exam(study):
    """Resolve a ``DicomStudy`` to ``(ConcessionService, unit)`` or ``None``.

    Requires BOTH a mapped service and a ``study.unit``. The study's DICOM
    modality code (e.g. "CT", "US") is matched to a ``ConcessionService`` by its
    ``modality`` field first, then by ``code`` (case-insensitive), among active
    services. Returns ``None`` if the study has no unit or no service matches.
    """
    from .models import ConcessionService

    unit = getattr(study, "unit", None)
    if unit is None:
        return None
    modality = (getattr(study, "modality", "") or "").strip()
    if not modality:
        return None
    service = (
        ConcessionService.objects.filter(active=True, modality__iexact=modality).first()
        or ConcessionService.objects.filter(active=True, code__iexact=modality).first()
    )
    if service is None:
        return None
    return (service, unit)


def _module_active() -> bool:
    """True when the current tenant has the ``diagnostic_concession`` module on.

    Fail-safe: any resolution error → treated as inactive (never blocks a save).
    """
    from apps.core.utils import tenant_has_feature

    from .permissions import CONCESSION_MODULE_KEY

    try:
        tenant = connection.tenant  # type: ignore[attr-defined]
        return tenant_has_feature(tenant, CONCESSION_MODULE_KEY)
    except Exception:
        logger.warning(
            "Could not resolve diagnostic_concession feature flag; treating as inactive.",
            exc_info=True,
        )
        return False


@receiver(post_save, sender="imaging.DicomStudy", dispatch_uid="concession_imaging_bridge")
def record_consumption_for_study(sender, instance, **kwargs):
    """Record an ``ExamConsumption`` for a just-saved ``DicomStudy``, defensively.

    No-op unless the module is active AND the study resolves to ``(service,
    unit)``. Idempotent per study, so a re-save never double-deducts. Any failure
    (insufficient stock, etc.) is swallowed and logged — it must NEVER roll back
    or block the study save (``record_exam_consumption`` is atomic, so its
    savepoint rolls back cleanly without partial deduction).
    """
    try:
        if not _module_active():
            return
        resolved = resolve_concession_exam(instance)
        if resolved is None:
            return
        service, unit = resolved

        from .services_pnl import record_exam_consumption

        record_exam_consumption(service, unit, dicom_study=instance)
    except Exception:
        logger.exception(
            "Concession imaging bridge failed for DicomStudy %s; failing safe.",
            getattr(instance, "pk", None),
        )


__all__ = ["resolve_concession_exam", "record_consumption_for_study"]
