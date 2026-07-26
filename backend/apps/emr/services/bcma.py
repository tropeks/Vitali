"""N3 — BCMA / eMAR beira-leito: the "5 certos" verifier.

*BCMA* (Barcode Medication Administration) is the bedside safety check nurses run
before recording a dose: scan the **patient** wristband and the **medication**
barcode, and confirm the "5 certos" against the signed order —

============  =================================================================
certo         verified here
============  =================================================================
paciente      scanned wristband barcode matches the patient (wristband or MRN)
medicamento   scanned medication barcode matches the ordered drug's barcode
dose          the order carries a structured, machine-verifiable dose
via           the order carries a structured administration route
hora          ``at_time`` falls inside the item's aprazamento window
============  =================================================================

:func:`verify_five_rights` is a **pure** function — no DB writes, no
``timezone.now()`` reads — so it is deterministic and trivially testable: the
same order + same scans + same ``at_time`` always yield the same verdict. The
caller (the eMAR check endpoint) decides what to do with a failing right: block,
or record an override with a justification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .aprazamento import generate_due_times

__all__ = [
    "verify_five_rights",
    "FiveRightsResult",
    "BCMA_TIME_TOLERANCE",
    "nearest_scheduled_slot",
]

# How far from a scheduled (aprazado) slot a bedside scan may still count as the
# "hora certa". ±60 min is the common eMAR administration window.
BCMA_TIME_TOLERANCE = timedelta(minutes=60)


@dataclass(frozen=True)
class FiveRightsResult:
    """Structured verdict of the five rights. ``ok`` iff every right passed."""

    patient: bool
    medication: bool
    dose: bool
    route: bool
    time: bool

    # Bare assignment (no annotation) → NOT a dataclass field, just a constant.
    RIGHTS = ("patient", "medication", "dose", "route", "time")

    @property
    def ok(self) -> bool:
        return all(getattr(self, right) for right in self.RIGHTS)

    @property
    def mismatches(self) -> list[str]:
        """Names of the rights that failed, in canonical order."""
        return [right for right in self.RIGHTS if not getattr(self, right)]

    def as_dict(self) -> dict:
        payload = {right: getattr(self, right) for right in self.RIGHTS}
        payload["ok"] = self.ok
        payload["mismatches"] = self.mismatches
        return payload


def _patient_right(patient, patient_barcode: str) -> bool:
    """Wristband scan identifies the patient (dedicated barcode, else MRN)."""
    scanned = (patient_barcode or "").strip()
    if not scanned:
        return False
    accepted = {
        (patient.wristband_barcode or "").strip(),
        (patient.medical_record_number or "").strip(),
    }
    accepted.discard("")
    return scanned in accepted


def _medication_right(prescription_item, medication_barcode: str) -> bool:
    """Scanned medication barcode matches the ordered drug's barcode."""
    scanned = (medication_barcode or "").strip()
    if not scanned:
        return False
    ordered = (getattr(prescription_item.drug, "barcode", None) or "").strip()
    return bool(ordered) and scanned == ordered


def _dose_right(prescription_item) -> bool:
    """The order carries a structured, machine-verifiable dose (> 0)."""
    dose = prescription_item.dose_amount
    return dose is not None and dose > 0


def _route_right(prescription_item) -> bool:
    """The order carries a structured administration route."""
    return bool((prescription_item.route or "").strip())


def _aprazamento_slots(prescription_item) -> list[datetime]:
    """Due (aprazado) times for the item over the 24h from its order anchor.

    Anchor = the prescription's ``signed_at`` (fallback ``created_at``). The
    interval derives from the structured ``frequency_per_day`` (e.g. 4×/day →
    6/6h); an order without a structured frequency is treated as a single due
    dose at the anchor.
    """
    prescription = prescription_item.prescription
    anchor = prescription.signed_at or prescription.created_at
    if anchor is None:
        return []
    freq = prescription_item.frequency_per_day
    if not freq or freq <= 0:
        return [anchor]
    return generate_due_times(anchor, 24 / freq, window_hours=24)


def _time_right(prescription_item, at_time: datetime) -> bool:
    """``at_time`` is within :data:`BCMA_TIME_TOLERANCE` of an aprazado slot."""
    slots = _aprazamento_slots(prescription_item)
    if not slots:
        return False
    return any(abs(at_time - slot) <= BCMA_TIME_TOLERANCE for slot in slots)


def nearest_scheduled_slot(prescription_item, at_time: datetime) -> datetime:
    """The aprazado (due) slot closest to ``at_time`` — the dose being given.

    The eMAR records one append-only event per (item, scheduled_at) slot, so the
    check endpoint resolves the bedside scan to the dose it fulfils. Falls back
    to ``at_time`` when the order exposes no schedule.
    """
    slots = _aprazamento_slots(prescription_item)
    if not slots:
        return at_time
    return min(slots, key=lambda slot: abs(at_time - slot))


def verify_five_rights(
    prescription_item,
    patient,
    *,
    patient_barcode: str,
    medication_barcode: str,
    at_time: datetime,
) -> FiveRightsResult:
    """Verify the "5 certos" for a bedside scan against a signed order.

    Pure and deterministic: reads only the passed order/patient and the scans;
    performs no writes and no clock reads.

    Args:
        prescription_item: the ordered :class:`PrescriptionItem` being administered.
        patient: the :class:`Patient` at the bedside (the order's patient).
        patient_barcode: value scanned off the patient wristband.
        medication_barcode: value scanned off the medication.
        at_time: the moment of administration to test against the aprazamento.

    Returns:
        A :class:`FiveRightsResult` with a per-right pass/fail and ``ok``.
    """
    return FiveRightsResult(
        patient=_patient_right(patient, patient_barcode),
        medication=_medication_right(prescription_item, medication_barcode),
        dose=_dose_right(prescription_item),
        route=_route_right(prescription_item),
        time=_time_right(prescription_item, at_time),
    )
