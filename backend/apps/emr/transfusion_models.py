"""
Banco de Sangue/Hemoterapia domain — requisição transfusional + prova de
compatibilidade (Sprint H3)
=============================================================================

H1 shipped the governed
:class:`~apps.core.blood_catalog_models.BloodComponentCatalog` catalog and the
tenant-side :class:`~apps.emr.bloodbank_models.BloodBag` stock. H3 adds the
**clinical order + reservation** layer that consumes that stock:

    TransfusionRequest (requisição)  ── FK order-parent + patient + hemocomponente
        └── CrossMatch (prova de compatibilidade)  ── FK BloodBag

* :class:`TransfusionRequest` — the médico's order for blood components for a
  patient, hung off exactly one order parent (encounter / admission /
  surgical_case / emergency_encounter). Governed cross-schema ``component`` FK to
  the SHARED catalog (DO_NOTHING + ``protect_blood_component_deletion``, mirroring
  ``BloodBag.component``). Status machine solicitada → reservada → liberada →
  transfundida, with cancelada reachable from any non-terminal state (see
  :mod:`apps.emr.services.transfusion`).
* :class:`CrossMatch` — the compatibility test between a request and a physical
  BloodBag. Records the ABO/Rh compatibility booleans + the crossmatch result and
  exposes a derived :pyattr:`compativel` (ABO AND Rh AND crossmatch compatible).

Reservation/liberation/cancellation are driven ONLY through
:mod:`apps.emr.services.transfusion` (atomic + ``select_for_update`` on the bag),
never raw ``serializer.save``, so the bag ``stock_status`` and the request
``status`` always move together. H4 (bedside checagem/reação) will consume a
``liberada`` request and drive the bag ``reservada`` → ``transfundida``.

Kept in a dedicated module (re-exported by ``models.py`` with a single
``from .transfusion_models import *``) so the parent-worktree merge touches
``models.py`` by exactly one line — mirroring ``bloodbank_models`` / ``adt_models``.
"""

from __future__ import annotations

import uuid

from django.db import models

__all__ = [
    "TransfusionRequest",
    "CrossMatch",
]


# ─── H3: requisição transfusional ────────────────────────────────────────────


class TransfusionRequest(models.Model):
    """A médico's order (requisição transfusional) for blood components.

    Hung off exactly one order parent (encounter / admission / surgical_case /
    emergency_encounter — each nullable, at least one required, enforced in
    :meth:`clean`). Classifies the requested hemocomponente via a governed
    cross-schema FK to the SHARED
    :class:`~apps.core.blood_catalog_models.BloodComponentCatalog`
    (DO_NOTHING + pre_delete PROTECT guard).
    """

    class Urgencia(models.TextChoices):
        ROTINA = "rotina", "Rotina"
        URGENCIA = "urgencia", "Urgência"
        EMERGENCIA = "emergencia", "Emergência"

    class Status(models.TextChoices):
        SOLICITADA = "solicitada", "Solicitada"
        RESERVADA = "reservada", "Reservada"
        LIBERADA = "liberada", "Liberada"
        TRANSFUNDIDA = "transfundida", "Transfundida"
        CANCELADA = "cancelada", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    patient = models.ForeignKey(
        "emr.Patient",
        on_delete=models.PROTECT,
        related_name="transfusion_requests",
        verbose_name="Paciente",
    )

    # ── order parents — at least one, each nullable (validated in clean) ──────
    encounter = models.ForeignKey(
        "emr.Encounter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfusion_requests",
        verbose_name="Atendimento",
    )
    admission = models.ForeignKey(
        "emr.Admission",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfusion_requests",
        verbose_name="Internação",
    )
    surgical_case = models.ForeignKey(
        "emr.SurgicalCase",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfusion_requests",
        verbose_name="Caso cirúrgico",
    )
    emergency_encounter = models.ForeignKey(
        "emr.EmergencyEncounter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfusion_requests",
        verbose_name="Boletim de emergência",
    )

    # ── governed cross-schema FK to the SHARED core.BloodComponentCatalog ─────
    # DO_NOTHING + protect_blood_component_deletion pre_delete signal, mirroring
    # emr.BloodBag.component.
    component = models.ForeignKey(
        "core.BloodComponentCatalog",
        on_delete=models.DO_NOTHING,
        related_name="+",
        verbose_name="Hemocomponente",
    )

    quantidade = models.PositiveIntegerField(
        "Quantidade (unidades)", help_text="Número de unidades solicitadas."
    )
    indicacao = models.TextField("Indicação clínica")
    cid = models.CharField("CID", max_length=10, blank=True, default="")
    urgencia = models.CharField(
        "Urgência",
        max_length=16,
        choices=Urgencia.choices,
        default=Urgencia.ROTINA,
        db_index=True,
    )

    requester = models.ForeignKey(
        "emr.Professional",
        on_delete=models.PROTECT,
        related_name="transfusion_requests",
        verbose_name="Solicitante",
    )

    status = models.CharField(
        "Situação",
        max_length=16,
        choices=Status.choices,
        default=Status.SOLICITADA,
        db_index=True,
    )

    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfusion_requests_created",
        verbose_name="Criado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Requisição Transfusional"
        verbose_name_plural = "Requisições Transfusionais"
        indexes = [
            models.Index(fields=["patient", "status"], name="emr_treq_patient_status_idx"),
            models.Index(fields=["status", "urgencia"], name="emr_treq_status_urg_idx"),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if not any(
            [
                self.encounter_id,
                self.admission_id,
                self.surgical_case_id,
                self.emergency_encounter_id,
            ]
        ):
            raise ValidationError(
                "A requisição transfusional precisa de ao menos um vínculo "
                "(atendimento, internação, caso cirúrgico ou boletim de emergência)."
            )

    def __str__(self):
        return f"Requisição {self.id} — {self.patient} ({self.get_status_display()})"


# ─── H3: prova de compatibilidade (crossmatch) ───────────────────────────────


class CrossMatch(models.Model):
    """A compatibility test (prova de compatibilidade) between a request and a bag.

    Records the ABO/Rh compatibility booleans plus the final crossmatch result;
    :pyattr:`compativel` is True only when ABO **and** Rh **and** the crossmatch
    result are all compatible. Created by the transfusion service on ``reservar``.
    """

    class Resultado(models.TextChoices):
        COMPATIVEL = "compativel", "Compatível"
        INCOMPATIVEL = "incompativel", "Incompatível"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    request = models.ForeignKey(
        TransfusionRequest,
        on_delete=models.CASCADE,
        related_name="crossmatches",
        verbose_name="Requisição",
    )
    bag = models.ForeignKey(
        "emr.BloodBag",
        on_delete=models.PROTECT,
        related_name="crossmatches",
        verbose_name="Bolsa",
    )

    abo_compativel = models.BooleanField("ABO compatível", default=False)
    rh_compativel = models.BooleanField("Rh compatível", default=False)
    crossmatch_resultado = models.CharField(
        "Resultado da prova cruzada",
        max_length=16,
        choices=Resultado.choices,
        default=Resultado.INCOMPATIVEL,
    )

    tested_at = models.DateTimeField("Testado em", auto_now_add=True)
    tested_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crossmatches_tested",
        verbose_name="Testado por",
    )
    notes = models.TextField("Observações", blank=True, default="")

    class Meta:
        ordering = ["-tested_at"]
        verbose_name = "Prova de Compatibilidade"
        verbose_name_plural = "Provas de Compatibilidade"
        indexes = [
            models.Index(fields=["request", "bag"], name="emr_xm_request_bag_idx"),
        ]

    @property
    def compativel(self) -> bool:
        """True only when ABO AND Rh AND the crossmatch result are all compatible."""
        return (
            self.abo_compativel
            and self.rh_compativel
            and self.crossmatch_resultado == self.Resultado.COMPATIVEL
        )

    def __str__(self):
        label = "compatível" if self.compativel else "incompatível"
        return f"Prova {self.id} — bolsa {self.bag_id} ({label})"
