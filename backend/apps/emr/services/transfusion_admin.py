"""
H4 — Checagem beira-leito + administração transfusional + hemovigilância service.

The bedside transfusion is driven ONLY through this module (never raw
``serializer.save``) so a :class:`~apps.emr.bloodbank_models.BloodBag`
``stock_status`` and the :class:`~apps.emr.transfusion_models.TransfusionRequest`
``status`` always advance together inside one ``transaction.atomic`` (with a
``select_for_update`` lock on the bag) — mirroring
:mod:`apps.emr.services.transfusion` and :mod:`apps.emr.services.adt`.

Flow (``checar_e_administrar``)
-------------------------------
1. The request must be ``liberada`` (else :class:`TransfusionStateError` → 409).
2. Run the pure transfusion "certos"
   (:func:`apps.emr.services.transfusion_checagem.verify_transfusion_rights`).
3. All certos pass → record a **verified** :class:`TransfusionAdministration`
   (``checagem_verified=True``) and advance request ``transfundida`` + bag
   ``transfundida``.
4. A certo fails **without** an ``override_reason`` → raise
   :class:`ChecagemFailedError` carrying the per-certo breakdown (the view returns
   422 with it), recording nothing.
5. A certo fails **with** an ``override_reason`` → record an **unverified**
   administration (``checagem_verified=False`` + the justification) and still
   advance the state (the nurse justified proceeding).

``registrar_reacao`` appends an append-only :class:`TransfusionReaction`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.emr.models import (
    BloodBag,
    TransfusionAdministration,
    TransfusionReaction,
    TransfusionRequest,
)

from .transfusion_checagem import verify_transfusion_rights

__all__ = [
    "checar_e_administrar",
    "registrar_reacao",
    "ChecagemFailedError",
    "TransfusionStateError",
]


class TransfusionStateError(ValidationError):
    """Illegal transition (e.g. checagem on a non-``liberada`` request) → HTTP 409."""


class ChecagemFailedError(ValidationError):
    """A transfusion certo failed and no override was given → HTTP 422.

    Carries the per-certo breakdown (``.checagem``) so the view can surface the
    exact failing rights alongside the 422.
    """

    def __init__(self, checagem: dict):
        self.checagem = checagem
        super().__init__(
            "Checagem beira-leito falhou; informe uma justificativa para prosseguir "
            "(exceção) ou corrija a leitura."
        )


@transaction.atomic
def checar_e_administrar(
    request: TransfusionRequest,
    bag: BloodBag,
    *,
    patient_barcode: str,
    bag_barcode: str,
    actor: Any = None,
    witness: Any = None,
    override_reason: str = "",
    at_time: datetime | None = None,
) -> TransfusionAdministration:
    """Run the bedside checagem and record the administration for ``request``/``bag``.

    Only from request status ``liberada``. Verified path advances request + bag to
    ``transfundida``; a failing certo without ``override_reason`` raises
    :class:`ChecagemFailedError` (recording nothing); with an override it records an
    unverified administration and still advances the state.

    Raises:
        TransfusionStateError: request is not ``liberada`` (→ 409).
        ChecagemFailedError: a certo failed and ``override_reason`` is empty (→ 422).
    """
    moment = at_time or timezone.now()

    locked_request = TransfusionRequest.objects.select_for_update().get(pk=request.pk)
    if locked_request.status != TransfusionRequest.Status.LIBERADA:
        raise TransfusionStateError(
            f"Requisição não está liberada (situação: "
            f"{locked_request.get_status_display()}); não pode ser transfundida."
        )

    locked_bag = BloodBag.objects.select_for_update().get(pk=bag.pk)

    result = verify_transfusion_rights(
        locked_request,
        locked_bag,
        patient_barcode=patient_barcode,
        bag_barcode=bag_barcode,
        at_time=moment,
    )

    if not result.ok and not (override_reason or "").strip():
        raise ChecagemFailedError(result.as_dict())

    administration = TransfusionAdministration.objects.create(
        request=locked_request,
        bag=locked_bag,
        patient=locked_request.patient,
        administered_by=actor,
        witness=witness,
        started_at=moment,
        status=TransfusionAdministration.Status.EM_ANDAMENTO,
        patient_barcode_scanned=(patient_barcode or "").strip(),
        bag_barcode_scanned=(bag_barcode or "").strip(),
        checagem_verified=result.ok,
        checagem_override_reason="" if result.ok else (override_reason or "").strip(),
    )

    locked_bag.stock_status = BloodBag.StockStatus.TRANSFUNDIDA
    locked_bag.save(update_fields=["stock_status", "updated_at"])

    locked_request.status = TransfusionRequest.Status.TRANSFUNDIDA
    locked_request.save(update_fields=["status", "updated_at"])

    return administration


@transaction.atomic
def registrar_reacao(
    administration: TransfusionAdministration,
    *,
    tipo: str,
    gravidade: str,
    descricao: str,
    conduta: str = "",
    notificado_hemovigilancia: bool = False,
    occurred_at: datetime | None = None,
    actor: Any = None,
) -> TransfusionReaction:
    """Append an adverse-reaction (hemovigilância) record to ``administration``."""
    return TransfusionReaction.objects.create(
        administration=administration,
        request=administration.request,
        tipo=tipo,
        gravidade=gravidade,
        descricao=descricao,
        conduta=conduta or "",
        notificado_hemovigilancia=notificado_hemovigilancia,
        occurred_at=occurred_at or timezone.now(),
        recorded_by=actor,
    )
