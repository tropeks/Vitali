"""H4 — Checagem beira-leito transfusional: the transfusion "certos" verifier.

Before hanging a blood component at the bedside, the nurse (2ª checagem de
enfermagem) confirms the transfusion "certos" against the released order — the
transfusion analogue of BCMA's "5 certos" (see :mod:`apps.emr.services.bcma`):

============  =================================================================
certo         verified here
============  =================================================================
paciente      scanned wristband barcode matches the request's patient (or MRN)
bolsa         scanned bag barcode matches the physical bag's identifier (DIN)
componente    the bag's hemocomponente matches the ordered component
compatibilidade  the bag's ABO+Rh is compatible with the patient (H3 rules)
validade      the bag has not expired (``expiry_date`` today or later)
============  =================================================================

:func:`verify_transfusion_rights` is a **pure** function — no DB writes — so it
is deterministic and trivially testable (same request + bag + scans + ``at_time``
→ same verdict). The caller (the checagem endpoint / service) decides what to do
with a failing right: block, or record an override with a justification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.utils import timezone

from .transfusion import abo_compativel, rh_compativel

__all__ = [
    "verify_transfusion_rights",
    "TransfusionRightsResult",
]


@dataclass(frozen=True)
class TransfusionRightsResult:
    """Structured verdict of the transfusion certos. ``ok`` iff every right passed."""

    paciente: bool
    bolsa: bool
    componente: bool
    compatibilidade: bool
    validade: bool

    # Bare assignment (no annotation) → NOT a dataclass field, just a constant.
    RIGHTS = ("paciente", "bolsa", "componente", "compatibilidade", "validade")

    @property
    def ok(self) -> bool:
        return all(getattr(self, right) for right in self.RIGHTS)

    @property
    def mismatches(self) -> list[str]:
        """Names of the certos that failed, in canonical order."""
        return [right for right in self.RIGHTS if not getattr(self, right)]

    def as_dict(self) -> dict:
        payload: dict[str, Any] = {right: getattr(self, right) for right in self.RIGHTS}
        payload["ok"] = self.ok
        payload["mismatches"] = self.mismatches
        return payload


def _paciente_right(patient, patient_barcode: str) -> bool:
    """Wristband scan identifies the request's patient (dedicated barcode, else MRN)."""
    scanned = (patient_barcode or "").strip()
    if not scanned:
        return False
    accepted = {
        (patient.wristband_barcode or "").strip(),
        (patient.medical_record_number or "").strip(),
    }
    accepted.discard("")
    return scanned in accepted


def _bolsa_right(bag, bag_barcode: str) -> bool:
    """Scanned bag barcode matches the physical bag's identifier (DIN)."""
    scanned = (bag_barcode or "").strip()
    if not scanned:
        return False
    identifier = (bag.identifier or "").strip()
    return bool(identifier) and scanned == identifier


def _componente_right(request, bag, component) -> bool:
    """The bag's hemocomponente matches the ordered component.

    ``component`` overrides the request's ordered component when given (e.g. a
    substitution explicitly authorised upstream); otherwise the request's own
    ``component`` is the expected one. Compared by pk to stay DB-free.
    """
    if component is not None:
        expected_id = getattr(component, "pk", component)
    else:
        expected_id = request.component_id
    return bag.component_id == expected_id


def _compatibilidade_right(patient, bag) -> bool:
    """ABO **and** Rh of the bag are compatible with the patient (reuse H3 rules)."""
    return abo_compativel(patient.abo, bag.abo) and rh_compativel(patient.rh_factor, bag.rh_factor)


def _resolve_today(at_time: datetime | date | None) -> date:
    if at_time is None:
        return timezone.now().date()
    if isinstance(at_time, datetime):
        return at_time.date()
    return at_time


def _validade_right(bag, today: date) -> bool:
    """The bag has not expired: ``expiry_date`` is today or later."""
    return bag.expiry_date is not None and bag.expiry_date >= today


def verify_transfusion_rights(
    request,
    bag,
    *,
    patient_barcode: str,
    bag_barcode: str,
    component=None,
    at_time: datetime | date | None = None,
) -> TransfusionRightsResult:
    """Verify the transfusion certos for a bedside checagem against a released order.

    Pure and deterministic: reads only the passed request/bag and the scans;
    performs no writes.

    Args:
        request: the :class:`TransfusionRequest` being fulfilled (carries patient
            + ordered ``component``).
        bag: the physical :class:`BloodBag` about to be hung.
        patient_barcode: value scanned off the patient wristband.
        bag_barcode: value scanned off the blood bag.
        component: optional expected hemocomponente override (else the request's).
        at_time: the moment of the checagem; its date anchors the validade check
            (falls back to ``timezone.now()`` when omitted).

    Returns:
        A :class:`TransfusionRightsResult` with a per-right pass/fail and ``ok``.
    """
    patient = request.patient
    today = _resolve_today(at_time)
    return TransfusionRightsResult(
        paciente=_paciente_right(patient, patient_barcode),
        bolsa=_bolsa_right(bag, bag_barcode),
        componente=_componente_right(request, bag, component),
        compatibilidade=_compatibilidade_right(patient, bag),
        validade=_validade_right(bag, today),
    )
