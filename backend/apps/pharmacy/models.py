"""
Pharmacy models — Farmácia & Estoque (Sprint 7)

S-026: Drug & Material Catalog
S-027: Stock Management (append-only ledger, Celery alerts)
S-028: Dispensation with FEFO lot selection
"""
import uuid
from decimal import Decimal

from django.db import models, transaction
from django.db.models import F
from django.utils import timezone


# ─── S-026: Catalog ───────────────────────────────────────────────────────────

class Drug(models.Model):
    """Medicamento cadastrado no sistema."""

    CONTROLLED_CHOICES = [
        ('none', 'Não controlado'),
        ('A1', 'Lista A1 — Entorpecentes'),
        ('A2', 'Lista A2 — Entorpecentes especiais'),
        ('A3', 'Lista A3 — Entorpecentes sujeitos a controle especial'),
        ('B1', 'Lista B1 — Psicotrópicos'),
        ('B2', 'Lista B2 — Psicotrópicos retinóides/anorexígenos'),
        ('C1', 'Lista C1 — Outras substâncias sujeitas a controle'),
        ('C2', 'Lista C2 — Retinóides de uso sistêmico'),
        ('C3', 'Lista C3 — Imunossupressores'),
        ('C4', 'Lista C4 — Antirretrovirais'),
        ('C5', 'Lista C5 — Anabolizantes'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=300, db_index=True)
    generic_name = models.CharField(max_length=300, blank=True, db_index=True)
    anvisa_code = models.CharField(max_length=20, blank=True, db_index=True)
    barcode = models.CharField(max_length=50, blank=True, unique=True, null=True)
    dosage_form = models.CharField(max_length=100, blank=True)
    concentration = models.CharField(max_length=100, blank=True)
    unit_of_measure = models.CharField(max_length=20, default='un')
    controlled_class = models.CharField(
        max_length=5, choices=CONTROLLED_CHOICES, default='none', db_index=True
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name', 'is_active']),
            models.Index(fields=['generic_name']),
            models.Index(fields=['controlled_class', 'is_active']),
        ]

    @property
    def is_controlled(self):
        return self.controlled_class != 'none'

    def __str__(self):
        return f'{self.name} ({self.dosage_form or "—"} {self.concentration or ""})'


class Material(models.Model):
    """Material médico-hospitalar (não medicamento)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=300, db_index=True)
    category = models.CharField(max_length=100, blank=True)
    barcode = models.CharField(max_length=50, blank=True, unique=True, null=True)
    unit_of_measure = models.CharField(max_length=20, default='un')
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.category or "—"})'


# ─── S-027: Stock ─────────────────────────────────────────────────────────────

class StockItem(models.Model):
    """
    Lote físico de um medicamento ou material em estoque.
    quantity é mantido via F() em StockMovement.save() — nunca editar diretamente.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    drug = models.ForeignKey(
        Drug, on_delete=models.PROTECT,
        null=True, blank=True, related_name='stock_items'
    )
    material = models.ForeignKey(
        Material, on_delete=models.PROTECT,
        null=True, blank=True, related_name='stock_items'
    )
    lot_number = models.CharField(max_length=50, blank=True, db_index=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0'))
    min_stock = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0'))
    location = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['expiry_date', 'lot_number']
        indexes = [
            models.Index(fields=['drug', 'expiry_date']),
            models.Index(fields=['material', 'expiry_date']),
            models.Index(fields=['expiry_date']),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(drug__isnull=False, material__isnull=True) |
                    models.Q(drug__isnull=True, material__isnull=False)
                ),
                name='stock_item_drug_xor_material',
            ),
            models.CheckConstraint(
                check=models.Q(quantity__gte=Decimal('0')),
                name='stock_item_quantity_non_negative',
            ),
        ]

    def __str__(self):
        item = self.drug or self.material
        return f'{item} — lote {self.lot_number} (qty: {self.quantity})'


class StockMovement(models.Model):
    """
    Ledger append-only de movimentações de estoque.
    quantity positivo = entrada, negativo = saída.
    Imutável após criação: save() rejeita updates, delete() levanta ValueError.
    """

    MOVEMENT_TYPES = [
        ('entry', 'Entrada'),
        ('dispense', 'Dispensação'),
        ('adjustment', 'Ajuste de inventário'),
        ('return', 'Devolução'),
        ('expired_write_off', 'Baixa por vencimento'),
        ('transfer', 'Transferência'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stock_item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name='movements')
    movement_type = models.CharField(max_length=30, choices=MOVEMENT_TYPES, db_index=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    reference = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        'core.User', on_delete=models.PROTECT, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("StockMovement entries are immutable — create a new one instead.")
        with transaction.atomic():
            super().save(*args, **kwargs)
            # Re-read current quantity inside the lock to verify non-negative result
            current = StockItem.objects.select_for_update().filter(pk=self.stock_item_id).values_list('quantity', flat=True).first()
            if current is not None and (current + self.quantity) < Decimal('0'):
                raise ValueError(
                    f'Movimento resultaria em estoque negativo: '
                    f'atual={current}, movimento={self.quantity}.'
                )
            StockItem.objects.filter(pk=self.stock_item_id).update(
                quantity=F('quantity') + self.quantity
            )

    def delete(self, *args, **kwargs):
        raise ValueError("StockMovement entries cannot be deleted — use an adjustment movement.")

    def __str__(self):
        return f'{self.get_movement_type_display()} {self.quantity} × {self.stock_item}'


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
        'emr.Prescription',
        on_delete=models.PROTECT,
        related_name='dispensations',
    )
    prescription_item = models.ForeignKey(
        'emr.PrescriptionItem',
        on_delete=models.PROTECT,
        related_name='dispensations',
    )
    patient = models.ForeignKey(
        'emr.Patient',
        on_delete=models.PROTECT,
        related_name='dispensations',
    )
    dispensed_by = models.ForeignKey(
        'core.User', on_delete=models.PROTECT, related_name='dispensations'
    )
    notes = models.TextField(blank=True)
    dispensed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-dispensed_at']
        indexes = [
            models.Index(fields=['patient', 'dispensed_at']),
            models.Index(fields=['prescription', 'dispensed_at']),
        ]

    @property
    def total_quantity(self):
        return sum(lot.quantity for lot in self.lots.all())

    def __str__(self):
        return f'Dispensação {self.id} — {self.patient} em {self.dispensed_at:%d/%m/%Y}'


class DispensationLot(models.Model):
    """
    Through-table: cada linha associa uma Dispensation a um StockItem (lote).
    Um único dispense pode consumir múltiplos lotes (FEFO).
    """

    dispensation = models.ForeignKey(
        Dispensation, on_delete=models.CASCADE, related_name='lots'
    )
    stock_item = models.ForeignKey(
        StockItem, on_delete=models.PROTECT, related_name='dispensation_lots'
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)

    class Meta:
        unique_together = [['dispensation', 'stock_item']]

    def __str__(self):
        return f'{self.dispensation_id} × {self.stock_item} — {self.quantity}'
