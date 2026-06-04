"""Controlled-diversion orchestrator — controlled-substance wedge PR C2.

Bridges the PURE engine (``apps.pharmacy.services.controlled_checker``) to the DB:
on each controlled dispensation it resolves the patient's PRIOR controlled history
(2 bounded queries, no N+1), runs the checker, and persists a ``ControlledAlert``
per signal. The engine DECIDES; this service persists. Mirrors the stockout /
no-show orchestrators.

POSTURE — ADVISE/compliance, NEVER blocks. It runs ``on_commit`` AFTER the
dispensation has committed (and after the DispenseView's 201), so it can never
delay or roll back a dispensation. Feature flag ``controlled_safety`` (default
OFF) → no-op. Fail-safe: any error is logged and swallowed.

Only CONTROLLED dispensations are evaluated; non-controlled drugs are ignored.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

from django.db import connection, transaction

from apps.core.models import AuditLog
from apps.core.utils import tenant_has_feature
from apps.pharmacy.services.controlled_checker import (
    ENGINE_VERSION,
    DispensationRecord,
    check,
)

logger = logging.getLogger(__name__)

CONTROLLED_SAFETY_FEATURE_KEY = "controlled_safety"


class ControlledSafetyService:
    def __init__(self, *, requesting_user=None) -> None:
        self.requesting_user = requesting_user
        self.correlation_id = str(uuid4())

    @classmethod
    def is_enabled(cls) -> bool:
        try:
            tenant = connection.tenant  # type: ignore[attr-defined]
            return tenant_has_feature(tenant, CONTROLLED_SAFETY_FEATURE_KEY)
        except Exception:
            logger.warning(
                "Could not resolve controlled_safety feature flag; defaulting to disabled.",
                exc_info=True,
            )
            return False

    def evaluate(self, dispensation_id) -> None:
        """Score a just-committed controlled dispensation. No-op / fail-safe."""
        if not self.is_enabled():
            return
        try:
            self._evaluate(dispensation_id)
        except Exception:
            logger.exception(
                "ControlledSafetyService.evaluate failed for dispensation %s; failing safe.",
                dispensation_id,
            )

    def _evaluate(self, dispensation_id) -> None:
        from apps.pharmacy.models import Dispensation, DispensationLot

        disp = (
            Dispensation.objects.select_related("prescription_item__drug", "prescription")
            .filter(pk=dispensation_id)
            .first()
        )
        if disp is None:
            return
        drug = disp.prescription_item.drug
        if drug is None or not drug.is_controlled:
            return  # only controlled drugs are monitored

        controlled_class = drug.controlled_class

        # Query 1: prior controlled dispensations of the SAME class for this patient.
        prior_raw = list(
            Dispensation.objects.filter(
                patient_id=disp.patient_id,
                dispensed_at__lt=disp.dispensed_at,
                prescription_item__drug__controlled_class=controlled_class,
            ).values_list(
                "id",
                "dispensed_at",
                "prescription_item__drug_id",
                "prescription__prescriber_id",
                "prescription_id",
            )
        )

        # Query 2: lot quantities for the current + prior dispensations, summed in
        # Python (NOT .values().annotate() — that trips a django-stubs/mypy crash).
        all_ids = [disp.id] + [row[0] for row in prior_raw]
        qty_by_disp: dict = defaultdict(lambda: Decimal("0"))
        for did, qty in DispensationLot.objects.filter(dispensation_id__in=all_ids).values_list(
            "dispensation_id", "quantity"
        ):
            qty_by_disp[did] += qty

        current = DispensationRecord(
            dispensation_id=str(disp.id),
            drug_id=str(drug.id),
            controlled_class=controlled_class,
            prescription_id=str(disp.prescription_id),
            prescriber_id=str(disp.prescription.prescriber_id)
            if disp.prescription.prescriber_id
            else None,
            quantity=qty_by_disp[disp.id],
            dispensed_at=disp.dispensed_at,
        )
        history = [
            DispensationRecord(
                dispensation_id=str(did),
                drug_id=str(drug_id),
                controlled_class=controlled_class,
                prescription_id=str(prescription_id),
                prescriber_id=str(prescriber_id) if prescriber_id else None,
                quantity=qty_by_disp[did],
                dispensed_at=dispensed_at,
            )
            for (did, dispensed_at, drug_id, prescriber_id, prescription_id) in prior_raw
        ]

        signals = check(
            current=current,
            history=history,
            min_refill_interval_days=drug.min_refill_interval_days,
        )
        for signal in signals:
            self._persist(disp, drug, signal)

    def _persist(self, disp, drug, signal) -> None:
        from apps.pharmacy.models import ControlledAlert

        with transaction.atomic():
            existing = (
                ControlledAlert.objects.select_for_update()
                .filter(dispensation=disp, signal_kind=signal.kind)
                .first()
            )
            # Override-preservation: an acknowledged alert with the same detail
            # stands on re-evaluation — don't reopen/spam.
            if (
                existing is not None
                and existing.status == ControlledAlert.Status.ACKNOWLEDGED
                and existing.detail == signal.detail
            ):
                return
            alert, _created = ControlledAlert.objects.update_or_create(
                dispensation=disp,
                signal_kind=signal.kind,
                defaults={
                    "patient_id": disp.patient_id,
                    "drug": drug,
                    "severity": ControlledAlert.Severity.ADVISE,
                    "detail": signal.detail,
                    "status": ControlledAlert.Status.OPEN,
                    "outcome": ControlledAlert.Outcome.PENDING,
                    "engine_version": signal.engine_version,
                    "acknowledged_by": None,
                    "acknowledged_at": None,
                    "note": "",
                },
            )
            self._audit(disp, drug, signal, alert.id)

    def _audit(self, disp, drug, signal, alert_id) -> None:
        AuditLog.objects.create(
            user=self.requesting_user,
            action=f"controlled_{signal.kind}",
            resource_type="controlled_alert",
            resource_id=str(alert_id),
            new_data={
                "correlation_id": self.correlation_id,
                "dispensation_id": str(disp.id),
                "patient_id": str(disp.patient_id),
                "drug": drug.name,
                "drug_id": str(drug.id),
                "signal_kind": signal.kind,
                "detail": signal.detail,
                "engine_version": ENGINE_VERSION,
            },
        )
