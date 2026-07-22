"""
Pharmacy models — Farmácia & Estoque (Sprint 7)

S-026: Drug & Material Catalog
S-027: Stock Management (append-only ledger, Celery alerts)
S-028: Dispensation with FEFO lot selection
"""

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from apps.core.constants import DOSE_UNIT_CHOICES, VOLUME_UNIT_CHOICES

# ─── S-026: Catalog ───────────────────────────────────────────────────────────


class Drug(models.Model):
    """Medicamento cadastrado no sistema."""

    CONTROLLED_CHOICES = [
        ("none", "Não controlado"),
        ("A1", "Lista A1 — Entorpecentes"),
        ("A2", "Lista A2 — Entorpecentes especiais"),
        ("A3", "Lista A3 — Entorpecentes sujeitos a controle especial"),
        ("B1", "Lista B1 — Psicotrópicos"),
        ("B2", "Lista B2 — Psicotrópicos retinóides/anorexígenos"),
        ("C1", "Lista C1 — Outras substâncias sujeitas a controle"),
        ("C2", "Lista C2 — Retinóides de uso sistêmico"),
        ("C3", "Lista C3 — Imunossupressores"),
        ("C4", "Lista C4 — Antirretrovirais"),
        ("C5", "Lista C5 — Anabolizantes"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=300, db_index=True)
    generic_name = models.CharField(max_length=300, blank=True, db_index=True)
    # Structured active ingredients (INN names) for the allergy-safety wedge — a
    # curated list (e.g. ["amoxicilina", "clavulanato"]) so the allergy engine can
    # match a recorded allergen against the drug's true components instead of
    # relying solely on the free-text name/generic_name. Empty list = uncurated →
    # the engine falls back to token-matching name+generic_name. Never invented:
    # populated by a human/import per establishment.
    active_ingredients = models.JSONField(default=list, blank=True)
    anvisa_code = models.CharField(max_length=20, blank=True, db_index=True)
    barcode = models.CharField(max_length=50, blank=True, unique=True, null=True)
    dosage_form = models.CharField(max_length=100, blank=True)
    concentration = models.CharField(max_length=100, blank=True)
    unit_of_measure = models.CharField(max_length=20, default="un")
    controlled_class = models.CharField(
        max_length=5, choices=CONTROLLED_CHOICES, default="none", db_index=True
    )
    # Controlled-diversion wedge (C1): minimum days between dispensations of THIS
    # drug to the same patient before a re-dispense is flagged as an early refill.
    # null → the refill-too-soon signal is INERT for this drug (no honest public
    # default exists — establishment-configured, never invented).
    min_refill_interval_days = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    # ── Stockout-prediction config (wedge S1) ─────────────────────────────────
    # All nullable → engine is INERT until the establishment supplies them. No
    # invented defaults: NULL means "no prediction", not "zero".
    lead_time_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Prazo de reposição do fornecedor (dias). NULL → predição inerte.",
    )
    safety_stock = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Estoque de segurança (unidades-buffer). NULL → não considerado.",
    )
    reorder_point = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Ponto de reposição explícito (unidades). NULL → não considerado.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name", "is_active"]),
            models.Index(fields=["generic_name"]),
            models.Index(fields=["controlled_class", "is_active"]),
        ]

    @property
    def is_controlled(self):
        return self.controlled_class != "none"

    def __str__(self):
        return f"{self.name} ({self.dosage_form or '—'} {self.concentration or ''})"


class Material(models.Model):
    """Material médico-hospitalar (não medicamento)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=300, db_index=True)
    category = models.CharField(max_length=100, blank=True)
    barcode = models.CharField(max_length=50, blank=True, unique=True, null=True)
    unit_of_measure = models.CharField(max_length=20, default="un")
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    # ── Stockout-prediction config (wedge S1) ─────────────────────────────────
    # All nullable → engine is INERT until the establishment supplies them. No
    # invented defaults: NULL means "no prediction", not "zero".
    lead_time_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Prazo de reposição do fornecedor (dias). NULL → predição inerte.",
    )
    safety_stock = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Estoque de segurança (unidades-buffer). NULL → não considerado.",
    )
    reorder_point = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Ponto de reposição explícito (unidades). NULL → não considerado.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.category or '—'})"


# ─── Allergy wedge PR A2: curated cross-reactivity classes ────────────────────


class AllergenClass(models.Model):
    """Curated allergen cross-reactivity class (allergy wedge A2).

    A named group of ingredients that cross-react — e.g. "Beta-lactâmicos" =
    ["penicilina", "amoxicilina", "ampicilina", "cefalexina", ...]. The allergy
    engine raises an **advise** (never block) cross-reactivity alert when the
    patient is allergic to one member of a class and the prescribed drug contains
    another member.

    Human-curated reference data — **inert until populated** (no class rows → no
    cross-reactivity checks), like the dose formulary. Never invented in code.
    Per-tenant so each establishment curates the classes its clinical pharmacy
    endorses.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    # Member ingredient names (INN). Free-form curated list; the engine matches a
    # member against an allergen/drug by normalized token-subset (same as A1).
    members = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True, db_index=True)
    # Provenance of imported reference data (loader source + version). Additive, blank default.
    source = models.CharField(max_length=200, blank=True)
    version = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Classe de reatividade cruzada"
        verbose_name_plural = "Classes de reatividade cruzada"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({len(self.members or [])} membros)"


class DrugInteraction(models.Model):
    """Curated drug-drug interaction pair (allergy wedge A3).

    A directional-agnostic pair of ingredients that interact — e.g.
    ("varfarina", "aas"). The allergy engine flags a prescription that contains
    BOTH ingredients (matched by normalized token-subset). ``severity`` decides
    the posture: ``advise`` (caution, surfaces only) or ``contraindicated``
    (blocks the soft-stop, override-with-reason).

    Human-curated — **inert until populated** (no rows → no interaction checks),
    like the dose formulary / cross-reactivity classes. Never invented in code.
    """

    class Severity(models.TextChoices):
        ADVISE = "advise", "Avisa"
        CONTRAINDICATED = "contraindicated", "Contraindicada (bloqueia)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ingredient_a = models.CharField(max_length=200)
    ingredient_b = models.CharField(max_length=200)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.ADVISE)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True, db_index=True)
    # Provenance of imported reference data (loader source + version). Additive, blank default.
    source = models.CharField(max_length=200, blank=True)
    version = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Interação medicamentosa"
        verbose_name_plural = "Interações medicamentosas"
        ordering = ["ingredient_a", "ingredient_b"]
        constraints = [
            models.UniqueConstraint(
                fields=["ingredient_a", "ingredient_b"], name="uniq_drug_interaction_pair"
            ),
        ]

    def __str__(self):
        return f"{self.ingredient_a} × {self.ingredient_b} ({self.get_severity_display()})"


# ─── S-027: Stock ─────────────────────────────────────────────────────────────


class StockItem(models.Model):
    """
    Lote físico de um medicamento ou material em estoque.
    quantity é mantido via F() em StockMovement.save() — nunca editar diretamente.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    drug = models.ForeignKey(
        Drug, on_delete=models.PROTECT, null=True, blank=True, related_name="stock_items"
    )
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, null=True, blank=True, related_name="stock_items"
    )
    lot_number = models.CharField(max_length=50, blank=True, db_index=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    min_stock = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    location = models.CharField(max_length=100, blank=True)
    warehouse = models.ForeignKey(
        "Warehouse", on_delete=models.PROTECT, null=True, blank=True, related_name="stock_items"
    )
    storage_location = models.ForeignKey(
        "StorageLocation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_items",
    )
    status = models.CharField(
        max_length=20,
        choices=(("available", "Disponível"), ("quarantine", "Quarentena"), ("recalled", "Recall")),
        default="available",
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["expiry_date", "lot_number"]
        indexes = [
            models.Index(fields=["drug", "expiry_date"]),
            models.Index(fields=["material", "expiry_date"]),
            models.Index(fields=["expiry_date"]),
        ]
        constraints = [
            # Taste Decision B (revised): UniqueConstraint with nulls_distinct=False enforces
            # uniqueness even when expiry_date is NULL — required for get_or_create safety in
            # concurrent PO receives. PostgreSQL's legacy UNIQUE treats NULL as distinct (not
            # equal), so unique_together would allow duplicate (drug, lot, NULL) rows.
            # Requires Django 5.0+ and PostgreSQL 15+. Both in use here (Django 5.2, PG 16).
            models.UniqueConstraint(
                fields=["drug", "lot_number", "expiry_date", "warehouse"],
                name="stockitem_drug_lot_expiry_unique",
                nulls_distinct=False,
            ),
            models.UniqueConstraint(
                fields=["material", "lot_number", "expiry_date", "warehouse"],
                name="stockitem_material_lot_expiry_unique",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(drug__isnull=False, material__isnull=True)
                    | models.Q(drug__isnull=True, material__isnull=False)
                ),
                name="stock_item_drug_xor_material",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=Decimal("0")),
                name="stock_item_quantity_non_negative",
            ),
        ]

    def __str__(self):
        item = self.drug or self.material
        return f"{item} — lote {self.lot_number} (qty: {self.quantity})"


class Warehouse(models.Model):
    """Unidade física de estoque; códigos são estáveis para integrações/WMS."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    active = models.BooleanField(default=True, db_index=True)
    controlled_substances = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("code",)

    def __str__(self):
        return f"{self.code} — {self.name}"


class StorageLocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="locations")
    code = models.CharField(max_length=60)
    name = models.CharField(max_length=160, blank=True)
    active = models.BooleanField(default=True)
    quarantine = models.BooleanField(default=False)

    class Meta:
        ordering = ("warehouse__code", "code")
        constraints = [
            models.UniqueConstraint(fields=("warehouse", "code"), name="uniq_storage_location")
        ]

    def __str__(self):
        return f"{self.warehouse.code}/{self.code}"


class StockMovement(models.Model):
    """
    Ledger append-only de movimentações de estoque.
    quantity positivo = entrada, negativo = saída.
    Imutável após criação: save() rejeita updates, delete() levanta ValueError.
    """

    MOVEMENT_TYPES = [
        ("entry", "Entrada"),
        ("purchase_order_receiving", "Recebimento de Pedido de Compra"),
        ("dispense", "Dispensação"),
        ("adjustment", "Ajuste de inventário"),
        ("return", "Devolução"),
        ("expired_write_off", "Baixa por vencimento"),
        ("transfer", "Transferência"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=30, choices=MOVEMENT_TYPES, db_index=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    reference = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    performed_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("StockMovement entries are immutable — create a new one instead.")
        with transaction.atomic():
            super().save(*args, **kwargs)
            # Re-read current quantity inside the lock to verify non-negative result
            current = (
                StockItem.objects.select_for_update()
                .filter(pk=self.stock_item_id)
                .values_list("quantity", flat=True)
                .first()
            )
            if current is not None and (current + self.quantity) < Decimal("0"):
                raise ValueError(
                    f"Movimento resultaria em estoque negativo: "
                    f"atual={current}, movimento={self.quantity}."
                )
            StockItem.objects.filter(pk=self.stock_item_id).update(
                quantity=F("quantity") + self.quantity
            )

    def delete(self, *args, **kwargs):
        raise ValueError("StockMovement entries cannot be deleted — use an adjustment movement.")

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity} × {self.stock_item}"


class InventoryCount(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SUBMITTED = "submitted", "Aguardando aprovação"
        APPROVED = "approved", "Aprovado e lançado"
        REJECTED = "rejected", "Rejeitado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="inventory_counts"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    blind = models.BooleanField(default=True, editable=False)
    requested_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="inventory_counts"
    )
    approval = models.OneToOneField(
        "governance.ApprovalRequest", on_delete=models.PROTECT, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Inventário {self.id} — {self.warehouse.code} ({self.status})"


class InventoryCountLine(models.Model):
    inventory = models.ForeignKey(InventoryCount, on_delete=models.CASCADE, related_name="lines")
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT)
    counted_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    system_quantity_snapshot = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, editable=False
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("inventory", "stock_item"), name="uniq_inventory_item")
        ]

    def __str__(self):
        return f"{self.inventory_id}: {self.stock_item_id} = {self.counted_quantity}"


class StockTransfer(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        IN_TRANSIT = "in_transit", "Em trânsito"
        ACCEPTED = "accepted", "Aceita"
        CANCELLED = "cancelled", "Cancelada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    origin = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="outgoing_transfers"
    )
    destination = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="incoming_transfers"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    requested_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="stock_transfers_requested"
    )
    accepted_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_transfers_accepted",
    )
    shipped_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(origin=models.F("destination")),
                name="transfer_distinct_warehouses",
            )
        ]

    def __str__(self):
        return f"Transferência {self.id}: {self.origin.code} → {self.destination.code}"


class StockTransferLine(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    source_item = models.ForeignKey(
        StockItem, on_delete=models.PROTECT, related_name="transfer_lines"
    )
    destination_item = models.ForeignKey(
        StockItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="received_transfer_lines",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)

    def __str__(self):
        return f"{self.transfer_id}: {self.quantity} × {self.source_item_id}"


class LotRecall(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        CLOSED = "closed", "Encerrado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lot_number = models.CharField(max_length=50, db_index=True)
    drug = models.ForeignKey(Drug, on_delete=models.PROTECT, null=True, blank=True)
    material = models.ForeignKey(Material, on_delete=models.PROTECT, null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey("core.User", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(drug__isnull=False, material__isnull=True)
                    | models.Q(drug__isnull=True, material__isnull=False)
                ),
                name="recall_drug_xor_material",
            )
        ]

    def __str__(self):
        return f"Recall {self.lot_number} ({self.status})"


# ─── S-028: Dispensation ──────────────────────────────────────────────────────


class Dispensation(models.Model):
    """
    Registro de dispensação — pode abranger múltiplos lotes (DispensationLot).
    total_quantity é a soma dos lotes (propriedade calculada, sem campo persistido).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Prescription FK uses string reference to avoid circular import at module load time.
    # apps.emr migration 0005 declares dependency on pharmacy 0001.
    prescription = models.ForeignKey(
        "emr.Prescription",
        on_delete=models.PROTECT,
        related_name="dispensations",
    )
    prescription_item = models.ForeignKey(
        "emr.PrescriptionItem",
        on_delete=models.PROTECT,
        related_name="dispensations",
    )
    patient = models.ForeignKey(
        "emr.Patient",
        on_delete=models.PROTECT,
        related_name="dispensations",
    )
    dispensed_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="dispensations"
    )
    notes = models.TextField(blank=True)
    dispensed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-dispensed_at"]
        indexes = [
            models.Index(fields=["patient", "dispensed_at"]),
            models.Index(fields=["prescription", "dispensed_at"]),
        ]

    @property
    def total_quantity(self):
        return sum(lot.quantity for lot in self.lots.all())

    def __str__(self):
        return f"Dispensação {self.id} — {self.patient} em {self.dispensed_at:%d/%m/%Y}"


class DispensationLot(models.Model):
    """
    Through-table: cada linha associa uma Dispensation a um StockItem (lote).
    Um único dispense pode consumir múltiplos lotes (FEFO).
    """

    dispensation = models.ForeignKey(Dispensation, on_delete=models.CASCADE, related_name="lots")
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.PROTECT, related_name="dispensation_lots"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        unique_together = [["dispensation", "stock_item"]]

    def __str__(self):
        return f"{self.dispensation_id} × {self.stock_item} — {self.quantity}"


# ─── Stockout-prediction wedge PR S2: persistent StockAlert ───────────────────


class StockAlert(models.Model):
    """Verdict do motor determinístico de ruptura/validade (wedge PR S2). Per-tenant.

    Mirror direto do ``billing.GlosaSafetyAlert``: linha de verdict do motor
    (``source="engine"``), ``UniqueConstraint`` para que a re-avaliação faça
    update_or_create no lugar (nunca duplica nem atropela um override
    reconhecido), e campos de ack para que um reconhecimento-com-justificativa
    permaneça. NÃO usa o cache Redis efêmero do StockAlertsView (que não dá
    flywheel) — esta é a linha persistente que o S3/S4 consomem.

    POSTURA — ADVISE, NUNCA BLOQUEIA. Previsão de suprimento jamais bloqueia
    dispensa clínica; a única severidade é ``advise`` (não há caminho ``block``).

    Alvo do alerta: o PRODUTO de catálogo (``drug`` XOR ``material``) — ruptura
    e validade são por produto. Para ``expiry_waste`` o ``stock_item`` aponta o
    lote específico que vence encalhado, com ``predicted_waste_qty``.
    """

    class Kind(models.TextChoices):
        STOCKOUT_RISK = "stockout_risk", "Risco de ruptura"
        EXPIRY_WASTE = "expiry_waste", "Desperdício por validade"

    class Severity(models.TextChoices):
        # Só "advise" é usado hoje; não há caminho de bloqueio para suprimento.
        ADVISE = "advise", "Avisa"

    class Source(models.TextChoices):
        ENGINE = "engine", "Motor determinístico"
        # Reservado: um futuro priorizador/explicador LLM escreveria source="llm"
        # aqui, espelhando o split engine|llm do GlosaSafetyAlert.
        LLM = "llm", "LLM (explicação)"

    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        ACKNOWLEDGED = "acknowledged", "Reconhecido"
        RESOLVED = "resolved", "Resolvido"

    class Outcome(models.TextChoices):
        """Rótulo do flywheel (wedge S4): o que ACONTECEU vs. o que foi previsto.

        Gravado pelo job noturno ``grade_stockout_predictions`` para cada
        predição de ``stockout_risk`` vencida. ``pending`` até a data-alvo
        passar. Subtileza crucial: uma predição INTERCEPTADA por um recebimento
        de pedido de compra NÃO é falso-positivo — o sistema funcionou (o
        gestor agiu sobre o aviso e a ruptura foi evitada).
        """

        PENDING = "pending", "Pendente (ainda não vencida)"
        TRUE_POSITIVE = "true_positive", "Acerto (estoque zerou)"
        INTERCEPTED = "intercepted", "Interceptado (reposição chegou)"
        FALSE_POSITIVE = "false_positive", "Falso-positivo (não zerou, sem reposição)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    drug = models.ForeignKey(
        Drug,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="stock_alerts",
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="stock_alerts",
    )
    # Lote-alvo do alerta de validade (NULL para stockout_risk, que é por produto).
    stock_item = models.ForeignKey(
        StockItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="stock_alerts",
        help_text="Lote específico para expiry_waste; NULL para stockout_risk.",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.ADVISE)
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.ENGINE,
        help_text="Qual checker produziu a linha: verdict 'engine' ou (futuro) 'llm'.",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    predicted_date = models.DateField(
        "Data prevista", null=True, blank=True, help_text="Ruptura ou vencimento previsto."
    )
    days_to_stockout = models.DecimalField(
        "Dias até ruptura", max_digits=10, decimal_places=1, null=True, blank=True
    )
    predicted_waste_qty = models.DecimalField(
        "Desperdício previsto", max_digits=12, decimal_places=3, null=True, blank=True
    )
    # Sugestão de reposição (wedge S3). Calculada pelo StockoutService na avaliação
    # (onde velocidade e saldo são conhecidos) APENAS para stockout_risk:
    #   ceil(velocidade * (lead_time_days + coverage_days) - saldo), clamp em ≥ 0.
    # NULL para expiry_waste e quando não há config suficiente. NÃO inventa dado de
    # fornecedor/contrato — só usa velocidade (derivada), lead_time (config) e saldo.
    suggested_reorder_qty = models.DecimalField(
        "Reposição sugerida",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Qtd sugerida p/ repor (stockout_risk): "
            "ceil(velocidade*(lead_time+cobertura)-saldo). NULL → sem sugestão."
        ),
    )
    engine_version = models.CharField(max_length=10, default="s2")
    # ── Flywheel grading (wedge S4) ───────────────────────────────────────────
    # Rótulo do que ACONTECEU vs. a predição. ``pending`` até a data-alvo
    # passar; o job noturno grada cada stockout_risk vencido exatamente uma vez
    # (graded_at marca o grading → idempotência). expiry_waste NÃO é gradado
    # por este job.
    outcome = models.CharField(
        "Resultado (flywheel)",
        max_length=20,
        choices=Outcome.choices,
        default=Outcome.PENDING,
        db_index=True,
        help_text="Rótulo do flywheel: o que aconteceu vs. o previsto. Gradado pelo job noturno.",
    )
    graded_at = models.DateTimeField(
        "Gradado em",
        null=True,
        blank=True,
        help_text="Quando o job de flywheel gradou esta predição. NULL → ainda não gradado.",
    )
    message = models.TextField("Mensagem (pt-BR)")
    acknowledged_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_stock_alerts",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Alerta de Estoque (motor)"
        verbose_name_plural = "Alertas de Estoque (motor)"
        ordering = ["-created_at"]
        constraints = [
            # Exatamente um de drug/material setado (alvo é o produto de catálogo).
            models.CheckConstraint(
                condition=(
                    models.Q(drug__isnull=False, material__isnull=True)
                    | models.Q(drug__isnull=True, material__isnull=False)
                ),
                name="stock_alert_drug_xor_material",
            ),
            # Uma linha por (drug, material, kind, source, stock_item) para que a
            # re-avaliação faça update_or_create no lugar e nunca atropele um
            # override reconhecido com uma duplicata. stock_item é NULL para
            # stockout_risk (alerta por produto) e setado para expiry_waste
            # (alerta por lote). Um UNIQUE legado do Postgres trata NULL como
            # DISTINTO, então as linhas de stockout_risk (stock_item IS NULL)
            # acumulariam duplicatas e quebrariam o update_or_create com
            # MultipleObjectsReturned. nulls_distinct=False (Django 5.0+ /
            # Postgres 15+; aqui Django 5.2, PG 16) faz NULL comparar IGUAL, então
            # a unicidade vale também para os alertas por produto. Mesma correção
            # de NULL do GlosaSafetyAlert / do UniqueConstraint do StockItem.
            models.UniqueConstraint(
                fields=["drug", "material", "kind", "source", "stock_item"],
                nulls_distinct=False,
                name="uniq_stock_alert",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "kind"]),
        ]

    @property
    def target(self):
        """O produto de catálogo que este alerta endereça (Drug ou Material)."""
        return self.drug or self.material

    def __str__(self):
        return f"{self.get_kind_display()} — {self.target} ({self.get_status_display()})"

    def acknowledge(self, user, note=""):
        self.acknowledged_by = user
        self.note = note
        self.acknowledged_at = timezone.now()
        self.status = self.Status.ACKNOWLEDGED
        self.save(update_fields=["acknowledged_by", "note", "acknowledged_at", "status"])


# ─── Controlled-diversion wedge PR C1: persistent ControlledAlert ─────────────


class ControlledAlert(models.Model):
    """Veredito do motor de diversão de controlados (wedge C1). Per-tenant.

    Mirror do ``StockAlert``: linha persistente do sinal determinístico
    (``source`` implícito = engine), com ``detail`` explicável e campos de
    flywheel + ack. POSTURA — **ADVISE/compliance, NUNCA bloqueia** a dispensa de
    controlado (o gate de permissão+notas do ``DispenseView`` já governa o ato).

    Uma dispensação pode levantar MÚLTIPLOS sinais (linhas separadas); a chave
    única ``(dispensation, signal_kind)`` faz a re-avaliação dar update no lugar.
    Risco DERIVADO do histórico; sem resolve-stale (o sinal é fato pontual).
    """

    class SignalKind(models.TextChoices):
        REFILL_TOO_SOON = "refill_too_soon", "Refill cedo demais"
        MULTIPLE_PRESCRIBERS = "multiple_prescribers", "Múltiplos prescritores"
        QUANTITY_ESCALATION = "quantity_escalation", "Escalada de quantidade"

    class Severity(models.TextChoices):
        ADVISE = "advise", "Avisa"

    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        ACKNOWLEDGED = "acknowledged", "Reconhecido"
        RESOLVED = "resolved", "Resolvido"

    class Outcome(models.TextChoices):
        PENDING = "pending", "Pendente"
        TRUE_POSITIVE = "true_positive", "Confirmado (diversão real)"
        FALSE_POSITIVE = "false_positive", "Falso-positivo"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dispensation = models.ForeignKey(
        Dispensation, on_delete=models.CASCADE, related_name="controlled_alerts"
    )
    patient = models.ForeignKey(
        "emr.Patient", on_delete=models.CASCADE, related_name="controlled_alerts"
    )
    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, related_name="controlled_alerts")
    signal_kind = models.CharField(max_length=24, choices=SignalKind.choices, db_index=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.ADVISE)
    detail = models.JSONField(default=dict)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.OPEN)
    outcome = models.CharField(
        max_length=16, choices=Outcome.choices, default=Outcome.PENDING, db_index=True
    )
    engine_version = models.CharField(max_length=40)
    acknowledged_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_controlled_alerts",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Alerta de Controlado (motor)"
        verbose_name_plural = "Alertas de Controlado (motor)"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["dispensation", "signal_kind"], name="uniq_controlled_alert"
            ),
        ]
        indexes = [
            models.Index(fields=["status", "signal_kind"]),
        ]

    def __str__(self):
        return f"{self.get_signal_kind_display()} — {self.drug} ({self.get_status_display()})"

    def acknowledge(self, user, note=""):
        self.acknowledged_by = user
        self.note = note
        self.acknowledged_at = timezone.now()
        self.status = self.Status.ACKNOWLEDGED
        self.save(update_fields=["acknowledged_by", "note", "acknowledged_at", "status"])


# ─── Dose-safety wedge PR A: Formulary & DoseRule ─────────────────────────────


class MedicationFormulary(models.Model):
    """
    Curated dose-checkable subset of the Drug catalog.

    The *existence* of a MedicationFormulary row is the "is this drug
    dose-checkable?" predicate: only drugs a pharmacist has curated (with a
    canonical strength + route) get a row. Drugs without a formulary row are
    NOT_APPLICABLE for the deterministic dose engine (PR B) — they pass with no
    dose badge. This is intentionally a separate table (not columns on Drug) so
    the curated clinical truth is decoupled from the general catalog.

    PR A is pure schema. No clinical numbers are seeded here — the curated
    formulary (≈8 high-alert drugs + their strengths) is pharmacist-supplied
    external truth, landing with the dose engine in PR B.
    """

    class Route(models.TextChoices):
        IV = "IV", "Intravenosa"
        IM = "IM", "Intramuscular"
        SC = "SC", "Subcutânea"
        PO = "PO", "Oral"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    drug = models.OneToOneField(
        Drug,
        on_delete=models.PROTECT,
        related_name="formulary",
        help_text="Drug this formulary entry curates. One row per drug = dose-checkable.",
    )
    strength_value = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        help_text="Canonical strength magnitude, e.g. 10.000 for '10 mg'.",
    )
    strength_unit = models.CharField(
        max_length=10,
        choices=DOSE_UNIT_CHOICES,
        help_text="Canonical mass unit (shared DOSE_UNIT_CHOICES): 'mg', 'mcg', 'mEq', 'unit', 'g'.",
    )
    volume_value = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="For injectables expressed per volume: the volume magnitude (e.g. 1.000).",
    )
    volume_unit = models.CharField(
        max_length=10,
        blank=True,
        choices=VOLUME_UNIT_CHOICES,
        help_text="Volume unit for injectables, e.g. 'mL' (strength is per this volume).",
    )
    route = models.CharField(
        max_length=4,
        choices=Route.choices,
        help_text="Canonical administration route for this formulary entry.",
    )
    is_injectable = models.BooleanField(default=False)
    is_high_alert = models.BooleanField(
        default=False,
        help_text="ISMP high-alert medication (heightened risk of significant patient harm).",
    )
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["drug__name"]
        verbose_name = "Medication Formulary Entry"
        verbose_name_plural = "Medication Formulary"

    def __str__(self):
        return f"{self.drug} — {self.strength_value}{self.strength_unit} {self.route}"


class DoseRule(models.Model):
    """
    A single dose-band rule for a formulary entry.

    ONE shape handles BOTH pediatric weight-based bands AND adult fixed-range
    rules, but the per-kg band and the absolute amounts are kept in SEPARATE,
    unambiguous fields (no unit paradox):

      - ``dose_unit`` is an ABSOLUTE MASS unit ONLY (mg/mcg/mEq/unit/g) — NEVER
        "mg/kg". A per-kg figure is expressed by ``basis="per_kg"`` + the per-kg
        fields, whose unit is implicitly ``dose_unit`` *per kg*.

      - basis="per_kg": the clinical band lives in ``min_per_kg`` / ``max_per_kg``
        (the per-kg lower AND upper bounds). ``max_per_kg`` is the per-kg overdose
        ceiling that was previously missing — a per-kg overdose under the absolute
        cap used to pass silently.

      - basis="fixed": the absolute band lives in ``min_per_dose`` /
        ``max_per_dose`` (a weight-independent single-dose range).

      - ``absolute_max_dose`` (NOT NULL) is the universal hard ceiling in
        ``dose_unit``, ALWAYS enforced regardless of basis. For per_kg rules it
        catches weight-entry typos (e.g. 70 kg typed 700 kg) that would otherwise
        sail past the per-kg math; for fixed rules it is the cap.

    Model-layer ``clean()`` enforces the per-basis invariants below; PR B's
    deterministic DoseChecker relies on them. PR A is pure schema — no clinical
    numbers are seeded.
    """

    class Basis(models.TextChoices):
        PER_KG = "per_kg", "Por kg de peso"
        FIXED = "fixed", "Dose fixa"

    class DoseRole(models.TextChoices):
        """Loading vs maintenance regimen (dose-engine v2, AXIS 2).

        A LOADING rule (e.g. vancomicina 25–30 mg/kg) is selected ONLY when the
        prescriber explicitly marks the item as loading. The default MAINTENANCE
        rule covers ordinary orders; an unmarked loading-magnitude dose is
        therefore screened against the lower maintenance band → over-flag
        (fail-safe), never a silent pass.
        """

        MAINTENANCE = "maintenance", "Manutenção"
        LOADING = "loading", "Ataque/Loading"

    class Enforcement(models.TextChoices):
        """Block vs advise on an out-of-range result (dose-engine v2, AXIS 3).

        BLOCK (default) → an OUT_OF_RANGE verdict raises a blocking 409 alert
        (today's behavior). ADVISE → an OUT_OF_RANGE verdict surfaces as a
        NON-blocking caution (for opioids/sedatives with no hard pharmacological
        ceiling — the "max" is an alert threshold, not a physical block). Note:
        WEIGHT_GATE and UNIT_MISMATCH remain blocking regardless of this field.
        """

        BLOCK = "block", "Bloquear"
        ADVISE = "advise", "Alertar (não bloqueante)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    formulary = models.ForeignKey(
        MedicationFormulary,
        on_delete=models.PROTECT,
        related_name="dose_rules",
    )
    basis = models.CharField(
        max_length=10,
        choices=Basis.choices,
        help_text="per_kg = dose scales with body weight; fixed = weight-independent.",
    )
    age_min_days = models.IntegerField(
        null=True,
        blank=True,
        help_text=(
            "Lower age bound in DAYS, inclusive. Null = unbounded. Days (not years) "
            "so neonatal/infant bands don't all collapse to 0y (18y ≈ 6570 days)."
        ),
    )
    age_max_days = models.IntegerField(
        null=True,
        blank=True,
        help_text="Upper age bound in DAYS, inclusive. Null = unbounded. (18y ≈ 6570 days.)",
    )
    weight_min_kg = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Lower weight bound (kg) for this band. Null = unbounded.",
    )
    weight_max_kg = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Upper weight bound (kg) for this band. Null = unbounded.",
    )
    dose_unit = models.CharField(
        max_length=10,
        choices=DOSE_UNIT_CHOICES,
        help_text=(
            "ABSOLUTE MASS unit for every numeric field here (shared DOSE_UNIT_CHOICES): "
            "mg/mcg/mEq/unit/g. NEVER 'mg/kg' — per-kg fields are implicitly this unit per kg."
        ),
    )
    # ─── per_kg band (basis="per_kg") — unit is dose_unit PER KG ──────────────
    min_per_kg = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Per-kg lower bound (in dose_unit per kg). Required when basis='per_kg'.",
    )
    max_per_kg = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=(
            "Per-kg UPPER bound (in dose_unit per kg). Required when basis='per_kg'. "
            "This is the per-kg overdose ceiling — without it a per-kg overdose that "
            "stays under absolute_max_dose would pass silently."
        ),
    )
    # ─── fixed band (basis="fixed") — absolute amounts in dose_unit ───────────
    min_per_dose = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Absolute minimum single dose (dose_unit). Required when basis='fixed'.",
    )
    max_per_dose = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Absolute maximum single dose (dose_unit). Required when basis='fixed'.",
    )
    # ─── universal hard ceiling — ALWAYS enforced ─────────────────────────────
    absolute_max_dose = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text=(
            "MANDATORY universal hard ceiling for a single administration, in dose_unit. "
            "ALWAYS enforced regardless of basis. For basis='per_kg' it catches weight-entry "
            "typos that would otherwise push the per-kg math past a safe absolute dose; for "
            "basis='fixed' it is the absolute cap."
        ),
    )
    max_per_day = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=(
            "Absolute maximum cumulative dose per day, in dose_unit (for max-daily checks in "
            "PR B). Null = none."
        ),
    )
    route = models.CharField(
        max_length=4,
        blank=True,
        help_text="Optional route this rule applies to; blank = any route on the formulary entry.",
    )
    # ─── AXIS 1: frequency band (dose-engine v2) ──────────────────────────────
    # Lets two rules coexist for the same drug/age that differ ONLY by regimen
    # frequency: e.g. gentamicina extended-interval (1×/dia, higher mg/kg) vs
    # traditional (2–4×/dia, lower mg/kg). Null bound = open (unbounded) on that
    # side. A rule with ANY freq bound set matches a prescribed frequency only
    # when it falls in [freq_min, freq_max]; if the prescription's frequency is
    # unknown, such a rule does NOT match (fail-safe — we can't confirm regimen).
    freq_min_per_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Lower bound (inclusive) on doses/day this rule applies to. Null = unbounded. "
            "Set together with freq_max_per_day to scope a rule to one regimen frequency."
        ),
    )
    freq_max_per_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Upper bound (inclusive) on doses/day this rule applies to. Null = unbounded.",
    )
    # ─── AXIS 2: loading vs maintenance (dose-engine v2) ──────────────────────
    dose_role = models.CharField(
        max_length=12,
        choices=DoseRole.choices,
        default=DoseRole.MAINTENANCE,
        help_text=(
            "maintenance (default) or loading. A loading rule is selected ONLY when the "
            "prescribed item is explicitly marked loading; otherwise the maintenance band applies."
        ),
    )
    # ─── AXIS 3: block vs advise enforcement (dose-engine v2) ─────────────────
    enforcement = models.CharField(
        max_length=10,
        choices=Enforcement.choices,
        default=Enforcement.BLOCK,
        help_text=(
            "block (default) → OUT_OF_RANGE raises a blocking 409; advise → OUT_OF_RANGE is a "
            "non-blocking caution (opioids/sedatives with no hard ceiling). WEIGHT_GATE / "
            "UNIT_MISMATCH always block regardless of this field."
        ),
    )
    active = models.BooleanField(default=True, db_index=True)
    # Validation gate — a DoseRule enforces ONLY when validated=True (human pharmacist
    # sign-off required). Default False = inert until a pharmacist explicitly validates
    # via the UI. The DoseChecker ignores rules with validated=False so that imported
    # or draft rules never silently enforce before clinical review.
    validated = models.BooleanField(default=False, db_index=True)
    validated_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(
        blank=True, help_text="Clinical citation / source for this rule (e.g. reference, dataset)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["formulary__drug__name", "age_min_days"]
        verbose_name = "Dose Rule"
        verbose_name_plural = "Dose Rules"
        constraints = [
            # Full natural-key uniqueness for the upsert in import_formulary.
            # nulls_distinct=False ensures that NULL band values compare equal,
            # so two rules that are identical except for both having NULL in the
            # same band column are treated as the same row (not as two distinct
            # rows — Postgres legacy UNIQUE treats NULL as distinct).
            # Requires Django 5.0+ + PostgreSQL 15+; both in use (Django 5.2, PG 16).
            models.UniqueConstraint(
                fields=[
                    "formulary",
                    "basis",
                    "dose_role",
                    "route",
                    "freq_min_per_day",
                    "freq_max_per_day",
                    "age_min_days",
                    "age_max_days",
                    "weight_min_kg",
                    "weight_max_kg",
                ],
                name="doserule_natural_key",
                nulls_distinct=False,
            ),
        ]

    def clean(self):
        """
        Enforce the per-basis invariants PR B's engine depends on:

          - absolute_max_dose is always required and must be > 0.
          - basis="per_kg" requires both min_per_kg and max_per_kg, with
            max_per_kg >= min_per_kg.
          - basis="fixed" requires both min_per_dose and max_per_dose, with
            max_per_dose >= min_per_dose.
        """
        errors = {}

        if self.absolute_max_dose is None:
            errors["absolute_max_dose"] = "absolute_max_dose is mandatory (the universal ceiling)."
        elif self.absolute_max_dose <= 0:
            errors["absolute_max_dose"] = "absolute_max_dose must be greater than 0."

        if self.basis == self.Basis.PER_KG:
            if self.min_per_kg is None:
                errors["min_per_kg"] = "min_per_kg is required when basis='per_kg'."
            if self.max_per_kg is None:
                errors["max_per_kg"] = "max_per_kg is required when basis='per_kg'."
            if (
                self.min_per_kg is not None
                and self.max_per_kg is not None
                and self.max_per_kg < self.min_per_kg
            ):
                errors["max_per_kg"] = "max_per_kg must be >= min_per_kg."
        elif self.basis == self.Basis.FIXED:
            if self.min_per_dose is None:
                errors["min_per_dose"] = "min_per_dose is required when basis='fixed'."
            if self.max_per_dose is None:
                errors["max_per_dose"] = "max_per_dose is required when basis='fixed'."
            if (
                self.min_per_dose is not None
                and self.max_per_dose is not None
                and self.max_per_dose < self.min_per_dose
            ):
                errors["max_per_dose"] = "max_per_dose must be >= min_per_dose."

        # AXIS 1: if BOTH frequency bounds are set, the band must be coherent.
        if (
            self.freq_min_per_day is not None
            and self.freq_max_per_day is not None
            and self.freq_max_per_day < self.freq_min_per_day
        ):
            errors["freq_max_per_day"] = "freq_max_per_day must be >= freq_min_per_day."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.formulary.drug} — {self.get_basis_display()} "
            f"(≤ {self.absolute_max_dose} {self.dose_unit})"
        )


# ─── S-042: Purchase Orders ───────────────────────────────────────────────────


class Supplier(models.Model):
    """Fornecedor de medicamentos e materiais."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Nome", max_length=200)
    cnpj = models.CharField("CNPJ", max_length=18, blank=True)
    contact_name = models.CharField("Contato", max_length=100, blank=True)
    contact_email = models.EmailField("E-mail", blank=True)
    contact_phone = models.CharField("Telefone", max_length=20, blank=True)
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Fornecedor"
        verbose_name_plural = "Fornecedores"

    def __str__(self):
        return self.name


class PurchaseOrder(models.Model):
    """Pedido de compra para reposição de estoque."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SENT = "sent", "Enviado ao fornecedor"
        PARTIAL = "partial", "Parcialmente recebido"
        RECEIVED = "received", "Recebido"
        CANCELLED = "cancelled", "Cancelado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    expected_date = models.DateField("Data prevista de entrega", null=True, blank=True)
    notes = models.TextField("Observações", blank=True)
    created_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, null=True, related_name="purchase_orders_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Pedido de Compra"
        verbose_name_plural = "Pedidos de Compra"

    def __str__(self):
        return f"PO-{str(self.id)[:8]} — {self.supplier.name} ({self.get_status_display()})"


class PurchaseOrderItem(models.Model):
    """Item de um pedido de compra (medicamento OU material, nunca ambos)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="items")
    drug = models.ForeignKey(
        Drug, on_delete=models.PROTECT, null=True, blank=True, related_name="po_items"
    )
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT, null=True, blank=True, related_name="po_items"
    )
    quantity_ordered = models.DecimalField("Qtd pedida", max_digits=12, decimal_places=3)
    quantity_received = models.DecimalField(
        "Qtd recebida", max_digits=12, decimal_places=3, default=Decimal("0")
    )
    unit_price = models.DecimalField("Preço unitário", max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(drug__isnull=False) | models.Q(material__isnull=False),
                name="po_item_must_have_drug_or_material",
            ),
            models.CheckConstraint(
                condition=~(models.Q(drug__isnull=False) & models.Q(material__isnull=False)),
                name="po_item_not_both",
            ),
        ]

    def __str__(self):
        item = self.drug or self.material
        return f"{item} × {self.quantity_ordered} (recebido: {self.quantity_received})"
