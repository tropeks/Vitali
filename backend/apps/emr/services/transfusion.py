"""
H3 — Requisição transfusional service: the reservation state machine.

Reserve / release / cancel are driven ONLY through this module (never raw
``serializer.save``) so a :class:`~apps.emr.bloodbank_models.BloodBag`
``stock_status`` and the :class:`~apps.emr.transfusion_models.TransfusionRequest`
``status`` always move together inside one ``transaction.atomic`` — mirroring
:mod:`apps.emr.services.adt`.

ABO/Rh compatibility rule (red-cell transfusion)
------------------------------------------------
A blood bag (donor unit) may be reserved for a patient (recipient) only when it
is BOTH ABO- and RhD-compatible. The recipient's plasma antibodies must not
attack the donor red cells:

* **ABO** — donor group must be in the recipient's compatible set:
    - recipient O   → only O          (O = universal donor)
    - recipient A   → A or O
    - recipient B   → B or O
    - recipient AB  → A, B, AB or O    (AB = universal recipient)
  This is the standard superset of the "same-ABO-or-O" rule.
* **RhD** — an Rh-**negative** recipient may receive only Rh-negative units
  (Rh-negative can give to Rh-positive, but not the reverse). An Rh-**positive**
  recipient may receive either.

A CrossMatch row is always created to record the outcome (compatible or not).
Only a compatible + available bag actually reserves; an incompatible or
unavailable bag raises ``ValidationError`` (→ 409 at the viewset) and reserves
nothing.

Status transitions (TransfusionRequest.status)
-----------------------------------------------
    solicitada ──reservar──▶ reservada ──liberar──▶ liberada ──▶ (transfundida: H4)
        │                        │                      │
        └──────────── cancelar ──┴──────────────────────┘
    cancelar: solicitada | reservada | liberada → cancelada (frees any reserved
    bag back to disponível). NOT allowed from transfundida or cancelada.
    reservar: only from solicitada. liberar: only from reservada.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.emr.models import BloodBag, CrossMatch, TransfusionRequest

# Recipient ABO group → set of donor ABO groups whose red cells are compatible.
_ABO_COMPATIBLE: dict[str, frozenset[str]] = {
    "O": frozenset({"O"}),
    "A": frozenset({"A", "O"}),
    "B": frozenset({"B", "O"}),
    "AB": frozenset({"A", "B", "AB", "O"}),
}


def abo_compativel(patient_abo: str, donor_abo: str) -> bool:
    """True when a ``donor_abo`` red-cell unit is ABO-compatible for ``patient_abo``."""
    return donor_abo in _ABO_COMPATIBLE.get(patient_abo, frozenset())


def rh_compativel(patient_rh: str, donor_rh: str) -> bool:
    """True when a ``donor_rh`` unit is RhD-compatible for ``patient_rh``.

    An Rh-negative recipient may receive only Rh-negative units; an Rh-positive
    recipient may receive either.
    """
    if patient_rh == "negativo":
        return donor_rh == "negativo"
    return True


@transaction.atomic
def reservar(
    request: TransfusionRequest,
    bag: BloodBag,
    *,
    actor: Any | None = None,
) -> CrossMatch:
    """Reserve ``bag`` for ``request``: run the compatibility check, always record
    a :class:`CrossMatch`, and — only when compatible — occupy the bag
    (``stock_status`` → reservada) and advance the request (``status`` → reservada).

    Locks the bag row (``select_for_update``) to serialize concurrent reservations.

    Raises ``ValidationError`` (→ 409) when the request is not ``solicitada``, the
    bag is not available (quarantine / already reserved / expired), or the bag is
    ABO/Rh-incompatible with the patient — reserving nothing in those cases.
    """
    locked_request = TransfusionRequest.objects.select_for_update().get(pk=request.pk)
    if locked_request.status != TransfusionRequest.Status.SOLICITADA:
        raise ValidationError(
            f"Requisição não está solicitada (situação: "
            f"{locked_request.get_status_display()}); não pode reservar bolsa."
        )

    locked_bag = BloodBag.objects.select_for_update().get(pk=bag.pk)
    if not locked_bag.is_available():
        raise ValidationError(
            f"Bolsa {locked_bag.identifier} indisponível para reserva "
            f"(sorologia: {locked_bag.get_serology_status_display()}, "
            f"estoque: {locked_bag.get_stock_status_display()})."
        )

    patient = locked_request.patient
    abo_ok = abo_compativel(patient.abo, locked_bag.abo)
    rh_ok = rh_compativel(patient.rh_factor, locked_bag.rh_factor)
    compat = abo_ok and rh_ok
    resultado = CrossMatch.Resultado.COMPATIVEL if compat else CrossMatch.Resultado.INCOMPATIVEL

    crossmatch = CrossMatch.objects.create(
        request=locked_request,
        bag=locked_bag,
        abo_compativel=abo_ok,
        rh_compativel=rh_ok,
        crossmatch_resultado=resultado,
        tested_by=actor,
    )

    if not compat:
        raise ValidationError(
            f"Bolsa {locked_bag.identifier} ({locked_bag.abo}{locked_bag.rh_factor}) "
            f"incompatível com o paciente ({patient.abo}{patient.rh_factor}): "
            f"ABO {'ok' if abo_ok else 'incompatível'}, "
            f"Rh {'ok' if rh_ok else 'incompatível'}."
        )

    locked_bag.stock_status = BloodBag.StockStatus.RESERVADA
    locked_bag.save(update_fields=["stock_status", "updated_at"])

    locked_request.status = TransfusionRequest.Status.RESERVADA
    locked_request.save(update_fields=["status", "updated_at"])

    return crossmatch


@transaction.atomic
def liberar(
    request: TransfusionRequest,
    *,
    actor: Any | None = None,
) -> TransfusionRequest:
    """Release a reserved request: ``reservada`` → ``liberada``.

    The reserved bag stays ``reservada`` (H4's bedside checagem marks it
    ``transfundida``). Raises ``ValidationError`` (→ 409) if the request is not
    ``reservada``.
    """
    locked = TransfusionRequest.objects.select_for_update().get(pk=request.pk)
    if locked.status != TransfusionRequest.Status.RESERVADA:
        raise ValidationError(
            f"Requisição não está reservada (situação: {locked.get_status_display()}); "
            f"não pode ser liberada."
        )
    locked.status = TransfusionRequest.Status.LIBERADA
    locked.save(update_fields=["status", "updated_at"])
    return locked


@transaction.atomic
def cancelar(
    request: TransfusionRequest,
    *,
    reason: str = "",
    actor: Any | None = None,
) -> TransfusionRequest:
    """Cancel a request: → ``cancelada``, freeing any bag reserved for it back to
    ``disponivel``.

    Allowed from ``solicitada`` / ``reservada`` / ``liberada``. Raises
    ``ValidationError`` (→ 409) from ``transfundida`` or ``cancelada`` (terminal).
    """
    locked = TransfusionRequest.objects.select_for_update().get(pk=request.pk)
    if locked.status in (
        TransfusionRequest.Status.TRANSFUNDIDA,
        TransfusionRequest.Status.CANCELADA,
    ):
        raise ValidationError(
            f"Requisição não pode ser cancelada (situação: {locked.get_status_display()})."
        )

    # Free any bag reserved for this request via a compatible crossmatch that is
    # still holding the bag in reservada.
    for crossmatch in locked.crossmatches.select_related("bag").all():
        if not crossmatch.compativel:
            continue
        bag = BloodBag.objects.select_for_update().get(pk=crossmatch.bag_id)
        if bag.stock_status == BloodBag.StockStatus.RESERVADA:
            bag.stock_status = BloodBag.StockStatus.DISPONIVEL
            bag.save(update_fields=["stock_status", "updated_at"])

    locked.status = TransfusionRequest.Status.CANCELADA
    locked.save(update_fields=["status", "updated_at"])
    return locked
