"""
Banco de Sangue/Hemoterapia domain — checagem beira-leito + administração +
reação transfusional / hemovigilância (Sprint H4)
=============================================================================

H3 shipped the clinical **order + reservation** layer (``TransfusionRequest`` /
``CrossMatch``). H4 adds the **bedside** layer that consumes a released
(``liberada``) request and drives the bag ``reservada`` → ``transfundida``:

    TransfusionAdministration (administração + checagem beira-leito)
        └── TransfusionReaction (reação transfusional / hemovigilância)

* :class:`TransfusionAdministration` — an **append-only** record of a nurse
  hanging a blood component at the bedside, gated by the transfusion "certos"
  checagem (:mod:`apps.emr.services.transfusion_checagem`). Persists the scanned
  patient/bag barcodes, whether the checagem fully verified, and — when a nurse
  proceeds past a failed right — the mandatory override justification. Two-person
  check via ``witness`` (2ª checagem de enfermagem). One active administration
  per request (partial-unique on ``em_andamento``).
* :class:`TransfusionReaction` — an **append-only** hemovigilância record of an
  adverse transfusion reaction, classified by ``tipo`` + ``gravidade``, with the
  ``notificado_hemovigilancia`` flag reserved for the NOTIVISA notification hook.

State moves ONLY through :mod:`apps.emr.services.transfusion_admin` (atomic +
``select_for_update`` on the bag) so the bag ``stock_status`` and the request
``status`` advance together.

Kept in a dedicated module (re-exported by ``models.py`` with a single
``from .transfusion_admin_models import *``) so the parent-worktree merge touches
``models.py`` by exactly one line — mirroring ``transfusion_models`` /
``bloodbank_models``. H3's ``transfusion_models.py`` is left untouched.
"""

from __future__ import annotations

import uuid

from django.db import models

__all__ = [
    "TransfusionAdministration",
    "TransfusionReaction",
]


# ─── H4: administração + checagem beira-leito ────────────────────────────────


class TransfusionAdministration(models.Model):
    """Append-only bedside administration of a blood component, gated by checagem.

    Created only through :func:`apps.emr.services.transfusion_admin.checar_e_administrar`
    after running the transfusion "certos". ``checagem_verified`` is True only when
    every certo passed; when the nurse proceeds past a failed right,
    ``checagem_verified`` stays False and ``checagem_override_reason`` carries the
    mandatory justification.
    """

    class Status(models.TextChoices):
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        CONCLUIDA = "concluida", "Concluída"
        INTERROMPIDA = "interrompida", "Interrompida"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    request = models.ForeignKey(
        "emr.TransfusionRequest",
        on_delete=models.PROTECT,
        related_name="administrations",
        verbose_name="Requisição",
    )
    bag = models.ForeignKey(
        "emr.BloodBag",
        on_delete=models.PROTECT,
        related_name="administrations",
        verbose_name="Bolsa",
    )
    patient = models.ForeignKey(
        "emr.Patient",
        on_delete=models.PROTECT,
        related_name="transfusion_administrations",
        verbose_name="Paciente",
    )

    administered_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        related_name="transfusion_administrations",
        verbose_name="Administrado por",
    )
    witness = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="witnessed_transfusion_administrations",
        verbose_name="Testemunha (2ª checagem)",
    )

    started_at = models.DateTimeField("Início", null=True, blank=True, db_index=True)
    finished_at = models.DateTimeField("Término", null=True, blank=True)
    volume_ml = models.PositiveIntegerField("Volume infundido (mL)", null=True, blank=True)
    status = models.CharField(
        "Situação",
        max_length=16,
        choices=Status.choices,
        default=Status.EM_ANDAMENTO,
        db_index=True,
    )

    # ─── checagem beira-leito: scan evidence for the transfusion "certos" ─────
    patient_barcode_scanned = models.CharField("Pulseira lida", max_length=64, blank=True)
    bag_barcode_scanned = models.CharField("DIN lido", max_length=64, blank=True)
    checagem_verified = models.BooleanField("Checagem verificada", default=False)
    checagem_override_reason = models.TextField("Justificativa da exceção", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Administração Transfusional"
        verbose_name_plural = "Administrações Transfusionais"
        constraints = [
            models.UniqueConstraint(
                fields=["request"],
                condition=models.Q(status="em_andamento"),
                name="emr_tadm_one_active_per_request",
            )
        ]
        indexes = [
            models.Index(fields=["request", "status"], name="emr_tadm_request_status_idx"),
        ]

    def __str__(self):
        label = "verificada" if self.checagem_verified else "exceção"
        return f"Administração {self.id} — bolsa {self.bag_id} ({label})"


# ─── H4: reação transfusional / hemovigilância ───────────────────────────────


class TransfusionReaction(models.Model):
    """Append-only hemovigilância record of an adverse transfusion reaction.

    Classified by ``tipo`` (natureza) + ``gravidade``. ``notificado_hemovigilancia``
    flags whether the reaction was notified to the hemovigilância authority
    (NOTIVISA hook — the notification transport is out of scope here).
    """

    class Tipo(models.TextChoices):
        FEBRIL_NAO_HEMOLITICA = "febril_nao_hemolitica", "Febril não hemolítica"
        ALERGICA = "alergica", "Alérgica"
        HEMOLITICA_AGUDA = "hemolitica_aguda", "Hemolítica aguda"
        TRALI = "trali", "TRALI (lesão pulmonar aguda)"
        TACO = "taco", "TACO (sobrecarga circulatória)"
        CONTAMINACAO_BACTERIANA = "contaminacao_bacteriana", "Contaminação bacteriana"
        OUTRA = "outra", "Outra"

    class Gravidade(models.TextChoices):
        LEVE = "leve", "Leve"
        MODERADA = "moderada", "Moderada"
        GRAVE = "grave", "Grave"
        OBITO = "obito", "Óbito"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    administration = models.ForeignKey(
        TransfusionAdministration,
        on_delete=models.PROTECT,
        related_name="reactions",
        verbose_name="Administração",
    )
    request = models.ForeignKey(
        "emr.TransfusionRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reactions",
        verbose_name="Requisição",
    )

    tipo = models.CharField("Tipo", max_length=32, choices=Tipo.choices, db_index=True)
    gravidade = models.CharField(
        "Gravidade", max_length=16, choices=Gravidade.choices, db_index=True
    )
    descricao = models.TextField("Descrição")
    conduta = models.TextField("Conduta", blank=True, default="")
    notificado_hemovigilancia = models.BooleanField("Notificado à hemovigilância", default=False)

    occurred_at = models.DateTimeField("Ocorrido em", db_index=True)
    recorded_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        related_name="transfusion_reactions",
        verbose_name="Registrado por",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "Reação Transfusional"
        verbose_name_plural = "Reações Transfusionais"
        indexes = [
            models.Index(fields=["administration"], name="emr_treac_adm_idx"),
            models.Index(fields=["tipo", "gravidade"], name="emr_treac_tipo_grav_idx"),
        ]

    def __str__(self):
        return f"Reação {self.get_tipo_display()} ({self.get_gravidade_display()})"
