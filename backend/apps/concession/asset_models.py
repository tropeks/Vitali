"""C1 — Frota em comodato (fleet on loan).

Ports the TCX asset domain (Asset / AssetService / AssetMovement /
MaintenanceTicket) into Vitali as tenant-local models of the diagnostic
concession module. The operator places imaging equipment ON LOAN at a client
Facility at its own cost and earns revenue from the exams it produces there,
so an asset is operator-owned, lives at a Facility, enables certain services,
and its maintenance is a tracked cost.

FKs use string references (``organization.Facility``, ``concession.
ConcessionService``, ``core.User``) to keep this module import-light and the
fan-out merge trivial.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

_TWO_PLACES = Decimal("0.01")


class EquipmentAsset(models.Model):
    """A piece of diagnostic-imaging equipment in the operator's fleet."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Ativo"
        IN_MAINTENANCE = "IN_MAINTENANCE", "Em manutenção"
        BACKUP = "BACKUP", "Reserva"
        WRITTEN_OFF = "WRITTEN_OFF", "Baixado"

    class Ownership(models.TextChoices):
        OPERATOR = "OPERATOR", "Operadora"
        CLIENT = "CLIENT", "Cliente"
        DOCTOR = "DOCTOR", "Médico"

    asset_tag = models.CharField("Patrimônio/tag", max_length=40, unique=True)
    name = models.CharField("Nome", max_length=200, blank=True)
    model = models.CharField("Modelo", max_length=120)
    serial_number = models.CharField("Número de série", max_length=120, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    ownership = models.CharField(
        max_length=20, choices=Ownership.choices, default=Ownership.OPERATOR
    )

    # Depreciation tracking
    purchase_cost = models.DecimalField(
        "Custo de aquisição", max_digits=12, decimal_places=2, null=True, blank=True
    )
    useful_life_months = models.PositiveIntegerField("Vida útil (meses)", null=True, blank=True)
    purchase_date = models.DateField("Data de aquisição", null=True, blank=True)

    # Nullable == at warehouse (not deployed to any client unit).
    current_location = models.ForeignKey(
        "organization.Facility",
        on_delete=models.SET_NULL,
        related_name="concession_assets",
        null=True,
        blank=True,
        help_text="Vazio = no armazém (não implantado).",
    )
    active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset_tag"]
        verbose_name = "Equipamento (comodato)"
        verbose_name_plural = "Equipamentos (comodato)"

    def __str__(self):
        return f"{self.asset_tag} — {self.model}"

    @property
    def monthly_depreciation(self) -> Decimal:
        """Linear monthly depreciation, quantized to 2 decimals.

        Returns ``0.00`` when purchase cost or useful life is missing.
        """
        if self.purchase_cost is None or not self.useful_life_months:
            return Decimal("0.00")
        return (self.purchase_cost / Decimal(self.useful_life_months)).quantize(
            _TWO_PLACES, rounding=ROUND_HALF_UP
        )


class AssetService(models.Model):
    """Junction: which services/exams an asset enables at its location."""

    asset = models.ForeignKey(
        EquipmentAsset, on_delete=models.CASCADE, related_name="enabled_services"
    )
    service = models.ForeignKey(
        "concession.ConcessionService", on_delete=models.PROTECT, related_name="enabling_assets"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["asset", "service"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "service"], name="concession_asset_service_unique"
            ),
        ]

    def __str__(self):
        return f"{self.asset_id} → {self.service_id}"


class AssetMovement(models.Model):
    """Append-only ledger of asset relocations; applies the move on create.

    Immutable: :meth:`save` refuses to persist an already-stored row and
    :meth:`delete` raises. Creating a movement relocates the asset (and, for
    SWAP, its counterpart).
    """

    class MovementType(models.TextChoices):
        DEPLOYMENT = "DEPLOYMENT", "Implantação"
        RETRIEVAL = "RETRIEVAL", "Recolhimento"
        TRANSFER = "TRANSFER", "Transferência"
        SWAP = "SWAP", "Troca"

    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    asset = models.ForeignKey(EquipmentAsset, on_delete=models.PROTECT, related_name="movements")

    from_facility = models.ForeignKey(
        "organization.Facility",
        on_delete=models.SET_NULL,
        related_name="concession_movements_from",
        null=True,
        blank=True,
    )
    to_facility = models.ForeignKey(
        "organization.Facility",
        on_delete=models.SET_NULL,
        related_name="concession_movements_to",
        null=True,
        blank=True,
    )
    # For SWAP: the counterpart asset whose location is exchanged with `asset`.
    swapped_with = models.ForeignKey(
        EquipmentAsset,
        on_delete=models.PROTECT,
        related_name="swap_movements",
        null=True,
        blank=True,
    )
    performed_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["asset"]),
            models.Index(fields=["movement_type"]),
        ]
        verbose_name = "Movimentação de equipamento"
        verbose_name_plural = "Movimentações de equipamento"

    def __str__(self):
        return f"{self.movement_type} — asset {self.asset_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError(
                "AssetMovement é um ledger append-only; atualização não é permitida."
            )
        super().save(*args, **kwargs)
        self._apply()

    def delete(self, *args, **kwargs):
        raise ValidationError("AssetMovement é um ledger append-only; remoção não é permitida.")

    def _apply(self):
        """Relocate the asset(s) according to this movement's type."""
        asset = self.asset
        if self.movement_type == self.MovementType.RETRIEVAL:
            asset.current_location = None
            asset.save(update_fields=["current_location", "updated_at"])
        elif self.movement_type in (
            self.MovementType.DEPLOYMENT,
            self.MovementType.TRANSFER,
        ):
            asset.current_location = self.to_facility
            asset.save(update_fields=["current_location", "updated_at"])
        elif self.movement_type == self.MovementType.SWAP:
            other = self.swapped_with
            if other is None:
                raise ValidationError("SWAP exige swapped_with (o equipamento contraparte).")
            asset.current_location, other.current_location = (
                other.current_location,
                asset.current_location,
            )
            asset.save(update_fields=["current_location", "updated_at"])
            other.save(update_fields=["current_location", "updated_at"])


class MaintenanceTicket(models.Model):
    """A maintenance/repair ticket; keeps the asset IN_MAINTENANCE while open."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Aberto"
        IN_PROGRESS = "IN_PROGRESS", "Em andamento"
        COMPLETED = "COMPLETED", "Concluído"
        CANCELLED = "CANCELLED", "Cancelado"

    asset = models.ForeignKey(
        EquipmentAsset, on_delete=models.PROTECT, related_name="maintenance_tickets"
    )
    facility = models.ForeignKey(
        "organization.Facility",
        on_delete=models.SET_NULL,
        related_name="concession_maintenance_tickets",
        null=True,
        blank=True,
    )
    description = models.TextField("Descrição do problema", blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    cost = models.DecimalField(
        "Custo do reparo", max_digits=12, decimal_places=2, null=True, blank=True
    )
    evidence_url = models.URLField("Evidência (foto)", blank=True)
    resolution = models.TextField("Resolução", blank=True)

    reported_by = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )
    assigned_to = models.ForeignKey(
        "core.User", on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["asset"]),
            models.Index(fields=["status"]),
        ]
        verbose_name = "Chamado de manutenção"
        verbose_name_plural = "Chamados de manutenção"

    def __str__(self):
        return f"MT asset {self.asset_id} — {self.status}"

    _OPEN_STATES = (Status.OPEN, Status.IN_PROGRESS)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._sync_asset_status()

    def _sync_asset_status(self):
        """Keep the asset's status in step with this ticket's lifecycle."""
        asset = self.asset
        if asset.status == EquipmentAsset.Status.WRITTEN_OFF:
            return
        if self.status in self._OPEN_STATES:
            if asset.status != EquipmentAsset.Status.IN_MAINTENANCE:
                asset.status = EquipmentAsset.Status.IN_MAINTENANCE
                asset.save(update_fields=["status", "updated_at"])
        else:  # COMPLETED / CANCELLED
            if asset.status == EquipmentAsset.Status.IN_MAINTENANCE:
                asset.status = EquipmentAsset.Status.ACTIVE
                asset.save(update_fields=["status", "updated_at"])

    def start(self, assigned_to=None):
        self.status = self.Status.IN_PROGRESS
        self.started_at = timezone.now()
        if assigned_to is not None:
            self.assigned_to = assigned_to
        self.save()

    def complete(self, resolution="", cost=None):
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        if resolution:
            self.resolution = resolution
        if cost is not None:
            self.cost = cost
        self.save()
