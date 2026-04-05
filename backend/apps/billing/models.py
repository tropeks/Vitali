"""
Billing Models — TISS/TUSS
==========================
Per-tenant (lives in each clinic's schema).

Cross-schema FK note: TUSSCode lives in the public schema. PostgreSQL does not
enforce referential integrity across schemas, so on_delete=PROTECT here is
application-layer enforcement only. A pre-delete signal on TUSSCode (see
apps/core/signals.py) compensates by checking live references.
"""

import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone


# ─── Choices ─────────────────────────────────────────────────────────────────

GUIDE_STATUS = [
    ("draft", "Rascunho"),
    ("pending", "Pendente envio"),
    ("submitted", "Enviado"),
    ("paid", "Pago"),
    ("denied", "Glosado"),
    ("appeal", "Em recurso"),
]

BATCH_STATUS = [
    ("open", "Aberto"),
    ("closed", "Fechado"),
    ("submitted", "Enviado"),
    ("processed", "Processado"),
]

GLOSA_REASON_CODES = [
    ("00", "Não informado"),
    ("01", "Procedimento não coberto"),
    ("02", "Incompatibilidade de sexo"),
    ("03", "Incompatibilidade de idade"),
    ("04", "Prazo de carência"),
    ("05", "Inconsistência nos dados do beneficiário"),
    ("99", "Outro"),
]

APPEAL_STATUS = [
    ("none", "Sem recurso"),
    ("filed", "Recurso enviado"),
    ("accepted", "Recurso aceito"),
    ("rejected", "Recurso rejeitado"),
]


# ─── Price / Provider ─────────────────────────────────────────────────────────

class InsuranceProvider(models.Model):
    """Operadora de saúde (convênio). Per-tenant."""

    name = models.CharField("Nome", max_length=200)
    ans_code = models.CharField("Código ANS", max_length=20, unique=True)
    cnpj = models.CharField("CNPJ", max_length=18, blank=True)
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Operadora"
        verbose_name_plural = "Operadoras"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (ANS {self.ans_code})"


class PriceTable(models.Model):
    """Tabela de preços negociada com uma operadora. Per-tenant."""

    provider = models.ForeignKey(
        InsuranceProvider, on_delete=models.CASCADE, related_name="price_tables"
    )
    name = models.CharField("Nome", max_length=100)
    valid_from = models.DateField("Válida a partir de")
    valid_until = models.DateField("Válida até", null=True, blank=True)
    is_active = models.BooleanField("Ativa", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tabela de Preços"
        verbose_name_plural = "Tabelas de Preços"
        unique_together = [("provider", "valid_from")]
        ordering = ["provider", "-valid_from"]

    def clean(self):
        # Prevent overlapping validity windows for the same provider.
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError(
                {"valid_until": "Data de fim deve ser posterior à data de início."}
            )
        qs = PriceTable.objects.filter(provider=self.provider).exclude(pk=self.pk)
        for other in qs:
            other_end = other.valid_until
            self_end = self.valid_until
            # open-ended table overlaps everything after its start
            if other_end is None or other_end >= self.valid_from:
                if self_end is None or self_end >= other.valid_from:
                    raise ValidationError(
                        f"Tabela de preços sobrepõe período com '{other.name}'"
                    )

    def save(self, *args, **kwargs):
        # Guarantee clean() runs on every save path (ORM, fixtures, tests).
        # Prevents overlapping validity windows from slipping past serializer validation.
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        until = self.valid_until.strftime("%m/%Y") if self.valid_until else "em aberto"
        return f"{self.name} ({self.valid_from.strftime('%m/%Y')} – {until})"


class PriceTableItem(models.Model):
    """Preço negociado por código TUSS em uma tabela. Per-tenant."""

    table = models.ForeignKey(
        PriceTable, on_delete=models.CASCADE, related_name="items"
    )
    # FK to public-schema TUSSCode — app-layer PROTECT only (cross-schema limit)
    tuss_code = models.ForeignKey(
        "core.TUSSCode", on_delete=models.PROTECT, related_name="price_table_items"
    )
    negotiated_value = models.DecimalField(
        "Valor negociado (R$)",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        verbose_name = "Item de Tabela"
        verbose_name_plural = "Itens de Tabela"
        unique_together = [("table", "tuss_code")]

    def __str__(self):
        return f"{self.tuss_code.code} — R${self.negotiated_value}"


# ─── TISS Guides ─────────────────────────────────────────────────────────────

class TISSGuide(models.Model):
    """
    Guia TISS — SP/SADT ou Consulta. Per-tenant.

    guide_number is generated atomically: YYYYMM + 6-digit sequence per tenant.
    insured_card_number is copied from PatientInsurance.card_number (decrypted)
    at guide-creation time; stored plain here because TISS XML requires it in
    plaintext anyway.
    """

    guide_number = models.CharField("Número da guia", max_length=20, unique=True, blank=True)
    guide_type = models.CharField(
        "Tipo",
        max_length=20,
        choices=[("sadt", "SP/SADT"), ("consulta", "Consulta")],
    )
    encounter = models.ForeignKey(
        "emr.Encounter", on_delete=models.PROTECT, related_name="tiss_guides"
    )
    patient = models.ForeignKey(
        "emr.Patient", on_delete=models.PROTECT, related_name="tiss_guides"
    )
    provider = models.ForeignKey(
        InsuranceProvider, on_delete=models.PROTECT, related_name="guides"
    )
    price_table = models.ForeignKey(
        PriceTable, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="guides"
    )
    status = models.CharField(
        "Status", max_length=20, choices=GUIDE_STATUS, default="draft", db_index=True
    )
    xml_content = models.TextField("XML da guia", blank=True)
    total_value = models.DecimalField(
        "Valor total (R$)", max_digits=12, decimal_places=2, default=0
    )
    # TISS mandatory fields
    insured_card_number = models.CharField("Número da carteirinha", max_length=20)
    authorization_number = models.CharField("Senha de autorização", max_length=20, blank=True)
    competency = models.CharField(
        "Competência (AAAA-MM)", max_length=7,
        help_text="Ex: 2026-03"
    )
    cid10_codes = models.JSONField(
        "Códigos CID-10", default=list,
        help_text='Lista de {"code": "X00"} do SOAPNote'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Guia TISS"
        verbose_name_plural = "Guias TISS"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["provider", "competency"]),
            models.Index(fields=["patient", "created_at"]),
        ]

    def generate_guide_number(self) -> str:
        """
        Generate sequential guide number: YYYYMM + 6-digit seq.
        Must be called inside an atomic block with select_for_update.
        """
        prefix = timezone.now().strftime("%Y%m")
        last = (
            TISSGuide.objects.select_for_update()
            .filter(guide_number__startswith=prefix)
            .order_by("-guide_number")
            .first()
        )
        seq = int(last.guide_number[6:]) + 1 if last else 1
        return f"{prefix}{seq:06d}"

    def save(self, *args, **kwargs):
        if not self.guide_number:
            from django.db import IntegrityError
            for _attempt in range(3):
                with transaction.atomic():
                    self.guide_number = self.generate_guide_number()
                    try:
                        super().save(*args, **kwargs)
                        return
                    except IntegrityError:
                        self.guide_number = ""
                        continue
            raise IntegrityError(
                "Failed to generate a unique guide number after 3 attempts."
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Guia {self.guide_number} — {self.patient}"


class TISSGuideItem(models.Model):
    """Procedimento/material em uma guia TISS. Per-tenant."""

    guide = models.ForeignKey(TISSGuide, on_delete=models.CASCADE, related_name="items")
    tuss_code = models.ForeignKey(
        "core.TUSSCode", on_delete=models.PROTECT, related_name="guide_items"
    )
    description = models.CharField("Descrição", max_length=300)
    quantity = models.DecimalField(
        "Quantidade", max_digits=8, decimal_places=2, default=1
    )
    unit_value = models.DecimalField("Valor unitário (R$)", max_digits=10, decimal_places=2)
    total_value = models.DecimalField("Valor total (R$)", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Item de Guia"
        verbose_name_plural = "Itens de Guia"

    def _recalc_guide_total(self):
        total = self.guide.items.aggregate(t=Sum("total_value"))["t"] or 0
        self.guide.total_value = total
        self.guide.save(update_fields=["total_value", "updated_at"])

    def save(self, *args, **kwargs):
        self.total_value = self.unit_value * self.quantity
        super().save(*args, **kwargs)
        self._recalc_guide_total()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._recalc_guide_total()

    def __str__(self):
        return f"{self.tuss_code.code} × {self.quantity} — Guia {self.guide.guide_number}"


# ─── TISS Batches ─────────────────────────────────────────────────────────────

class TISSBatch(models.Model):
    """
    Lote TISS — agrupa guias para envio a uma operadora. Per-tenant.

    Double-submit protection: a guide already in a closed/submitted batch
    cannot be added to another batch (enforced in clean()).
    """

    batch_number = models.CharField("Número do lote", max_length=20, unique=True, blank=True)
    provider = models.ForeignKey(
        InsuranceProvider, on_delete=models.PROTECT, related_name="batches"
    )
    guides = models.ManyToManyField(TISSGuide, related_name="batches", blank=True)
    status = models.CharField(
        "Status", max_length=20, choices=BATCH_STATUS, default="open", db_index=True
    )
    xml_file = models.CharField("Arquivo XML (path)", max_length=500, blank=True)
    retorno_xml_file = models.CharField(
        "Retorno XML (path)", max_length=500, blank=True,
        help_text="Path to the raw retorno XML from the insurer — stored for audit trail."
    )
    total_value = models.DecimalField(
        "Valor total (R$)", max_digits=14, decimal_places=2, default=0
    )
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Lote TISS"
        verbose_name_plural = "Lotes TISS"
        ordering = ["-created_at"]

    def generate_batch_number(self) -> str:
        prefix = timezone.now().strftime("%Y%m")
        last = (
            TISSBatch.objects.select_for_update()
            .filter(batch_number__startswith=prefix)
            .order_by("-batch_number")
            .first()
        )
        seq = int(last.batch_number[6:]) + 1 if last else 1
        return f"{prefix}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.batch_number:
            from django.db import IntegrityError
            for _attempt in range(3):
                with transaction.atomic():
                    self.batch_number = self.generate_batch_number()
                    try:
                        super().save(*args, **kwargs)
                        return
                    except IntegrityError:
                        self.batch_number = ""
                        continue
            raise IntegrityError(
                "Failed to generate a unique batch number after 3 attempts."
            )
        else:
            super().save(*args, **kwargs)

    def check_guide_not_double_submitted(self, guide: TISSGuide) -> None:
        """Raise ValidationError if the guide is already in a closed/submitted batch."""
        conflict = (
            TISSBatch.objects.filter(
                guides=guide,
                status__in=["closed", "submitted"],
            )
            .exclude(pk=self.pk)
            .first()
        )
        if conflict:
            raise ValidationError(
                f"Guia {guide.guide_number} já consta no lote {conflict.batch_number} "
                f"(status: {conflict.get_status_display()}). Double-billing bloqueado."
            )

    def __str__(self):
        return f"Lote {self.batch_number} — {self.provider.name}"


def _tissbatch_m2m_changed(sender, instance, action, pk_set, **kwargs):
    """
    Enforce double-submit protection when guides are added via M2M directly
    (bypasses the serializer layer). Runs on m2m_changed signal for
    TISSBatch.guides through-table.
    """
    if action != "pre_add" or not pk_set:
        return
    for guide_pk in pk_set:
        try:
            guide = TISSGuide.objects.get(pk=guide_pk)
        except TISSGuide.DoesNotExist:
            continue
        instance.check_guide_not_double_submitted(guide)


from django.db.models.signals import m2m_changed  # noqa: E402
m2m_changed.connect(_tissbatch_m2m_changed, sender=TISSBatch.guides.through)


# ─── S-055: PIX Payment ───────────────────────────────────────────────────────


class PIXCharge(models.Model):
    """
    Tracks a PIX payment charge created via Asaas for a self-pay appointment.
    Per-tenant schema.

    Lifecycle: pending → paid (via webhook) | expired (via Celery beat at expires_at)
                        ↘ refunded (manual, Phase 2)

    LGPD note: we store asaas_customer_id (not raw CPF). The mapping from
    Patient → Asaas customer ID is maintained in AsaasService.get_or_create_customer().
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Aguardando pagamento"
        PAID = "paid", "Pago"
        EXPIRED = "expired", "Expirado"
        CANCELLED = "cancelled", "Cancelado"
        REFUNDED = "refunded", "Estornado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(
        "emr.Appointment",
        on_delete=models.CASCADE,
        related_name="pix_charge",
    )
    # Asaas identifiers — no raw CPF stored
    asaas_charge_id = models.CharField("Asaas Charge ID", max_length=100, unique=True)
    asaas_customer_id = models.CharField("Asaas Customer ID", max_length=100, blank=True)
    # Payment data
    amount = models.DecimalField("Valor (R$)", max_digits=10, decimal_places=2)
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    pix_copy_paste = models.TextField("Código PIX copia e cola", blank=True)
    pix_qr_code_base64 = models.TextField("QR Code (base64)", blank=True)
    expires_at = models.DateTimeField("Expira em")
    paid_at = models.DateTimeField("Pago em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cobrança PIX"
        verbose_name_plural = "Cobranças PIX"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["asaas_charge_id"]),
        ]

    def __str__(self):
        return f"PIX {self.asaas_charge_id} — R${self.amount} ({self.get_status_display()})"




# ─── Glosas ───────────────────────────────────────────────────────────────────

class Glosa(models.Model):
    """Registro de glosa (negativa/ajuste) de uma guia pela operadora. Per-tenant."""

    guide = models.ForeignKey(TISSGuide, on_delete=models.CASCADE, related_name="glosas")
    guide_item = models.ForeignKey(
        TISSGuideItem, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="glosas"
    )
    reason_code = models.CharField(
        "Código de motivo", max_length=5, choices=GLOSA_REASON_CODES
    )
    reason_description = models.TextField("Descrição do motivo")
    value_denied = models.DecimalField(
        "Valor glosado (R$)", max_digits=12, decimal_places=2
    )
    appeal_status = models.CharField(
        "Status do recurso", max_length=20, choices=APPEAL_STATUS, default="none"
    )
    appeal_text = models.TextField("Texto do recurso", blank=True)
    appeal_filed_at = models.DateTimeField("Recurso enviado em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Glosa"
        verbose_name_plural = "Glosas"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"Glosa {self.get_reason_code_display()} — Guia {self.guide.guide_number} "
            f"R${self.value_denied}"
        )
