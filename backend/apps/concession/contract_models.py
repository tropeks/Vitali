"""Sprint C2 — Contrato all-inclusive + recipe + preço (economic core).

The operator's revenue is EXAM VOLUME × price, so a contract fixes, per client/
unit, the price of each service (``ContractServicePrice``) — with an
``is_billable`` flag so an *included* exam still counts volume even when its
direct revenue is zero. Each service also CONSUMES supplies
(``ServiceRecipe``: service → N of a ``pharmacy.Material``), the cost driver.
Together they feed the concession P&L (revenue vs. consumption).

Design note — tenancy: these models are tenant-local (django-tenants schema per
tenant), like ``ConcessionService``. No ``organization`` FK is added for scoping:
the schema already isolates tenants, and TCX's ``organizationId`` only exists
because TCX is single-schema multi-tenant. FKs to ``pharmacy.Material`` and
``organization.Facility`` are safe — those apps live in the same tenant schema.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models

from .models import ConcessionService


class ConcessionContract(models.Model):
    """All-inclusive concession contract with a client, spanning one or more
    units (Facilities), with an optional fixed monthly value and a vigency."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Ativo"
        EXPIRED = "EXPIRED", "Expirado"
        TERMINATED = "TERMINATED", "Rescindido"

    name = models.CharField("Nome do contrato", max_length=200)
    client_name = models.CharField("Cliente", max_length=200, blank=True)
    # Optional structured client (same tenant schema). Kept nullable: many
    # contracts are captured by name before the legal entity is registered.
    client = models.ForeignKey(
        "organization.LegalEntity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="concession_contracts",
        verbose_name="Cliente (entidade legal)",
    )
    units = models.ManyToManyField(
        "organization.Facility",
        related_name="concession_contracts",
        blank=True,
        verbose_name="Unidades",
    )
    monthly_value = models.DecimalField(
        "Valor mensal",
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Valor fixo mensal do contrato (opcional).",
    )
    start_date = models.DateField("Início da vigência")
    end_date = models.DateField("Fim da vigência", null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Contrato de concessão"
        verbose_name_plural = "Contratos de concessão"

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def resolve_price(self, service: ConcessionService, unit=None) -> ContractServicePrice | None:
        """Resolve the applicable price row for *service* at *unit*.

        A unit-level price (``ContractServicePrice`` scoped to the Facility)
        overrides the contract-level price. Returns the ``ContractServicePrice``
        row (so callers can read ``price`` and ``is_billable``) or ``None`` when
        no price is configured. The row resolves even when ``is_billable`` is
        False — exam volume still counts; only billable *revenue* is zeroed.
        """
        if unit is not None:
            unit_price = ContractServicePrice.objects.filter(unit=unit, service=service).first()
            if unit_price is not None:
                return unit_price
        return ContractServicePrice.objects.filter(contract=self, service=service).first()


class ContractServicePrice(models.Model):
    """Price of one service, scoped to a contract and/or a unit.

    Revenue for the operator. ``is_billable=False`` means the exam is included
    (revenue 0) but its volume still counts — the row still resolves.
    """

    contract = models.ForeignKey(
        ConcessionContract,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="prices",
        verbose_name="Contrato",
    )
    unit = models.ForeignKey(
        "organization.Facility",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="concession_service_prices",
        verbose_name="Unidade",
    )
    service = models.ForeignKey(
        ConcessionService,
        on_delete=models.PROTECT,
        related_name="contract_prices",
        verbose_name="Serviço",
    )
    price = models.DecimalField("Preço", max_digits=12, decimal_places=2)
    is_billable = models.BooleanField(
        "Faturável",
        default=True,
        help_text="Se falso, a receita é 0 mas o volume ainda conta.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["service__code"]
        verbose_name = "Preço de serviço do contrato"
        verbose_name_plural = "Preços de serviço do contrato"
        constraints = [
            # One price per service per contract, and per service per unit.
            # NULLs are distinct in Postgres, so contract-only and unit-only
            # rows coexist without collision.
            models.UniqueConstraint(
                fields=["contract", "service"], name="concession_price_contract_service_unique"
            ),
            models.UniqueConstraint(
                fields=["unit", "service"], name="concession_price_unit_service_unique"
            ),
        ]

    def __str__(self):
        scope = self.unit_id and "unit" or "contract"
        return f"{self.service_id} @ {self.price} ({scope})"

    @property
    def billable_revenue(self) -> Decimal:
        """Revenue this price contributes: ``price`` if billable, else 0.

        Volume still counts upstream — only revenue is zeroed here.
        """
        return self.price if self.is_billable else Decimal("0")


class ServiceRecipe(models.Model):
    """A service consumes N of a ``pharmacy.Material`` per exam — the cost driver."""

    service = models.ForeignKey(
        ConcessionService,
        on_delete=models.CASCADE,
        related_name="recipes",
        verbose_name="Serviço",
    )
    material = models.ForeignKey(
        "pharmacy.Material",
        on_delete=models.PROTECT,
        related_name="concession_recipes",
        verbose_name="Insumo",
    )
    quantity = models.DecimalField(
        "Quantidade por exame",
        max_digits=12,
        decimal_places=3,
        default=Decimal("1"),
        help_text="Quantidade do insumo consumida por exame.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["service__code", "material__name"]
        verbose_name = "Receita de serviço (insumo)"
        verbose_name_plural = "Receitas de serviço (insumos)"
        constraints = [
            models.UniqueConstraint(
                fields=["service", "material"], name="concession_recipe_service_material_unique"
            ),
        ]

    def __str__(self):
        return f"{self.service_id}: {self.quantity} × {self.material_id}"


def consumption_for(service: ConcessionService) -> dict:
    """Return the ``{material: quantity_per_exam}`` map for *service*.

    The cost driver: one exam of *service* consumes ``quantity`` of each mapped
    ``pharmacy.Material``. Multiply by exam volume to size total consumption.
    """
    return {
        recipe.material: recipe.quantity
        for recipe in ServiceRecipe.objects.filter(service=service).select_related("material")
    }
