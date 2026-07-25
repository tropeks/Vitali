"""
Billing — Revenue-cycle models (Sprint M1-S4)
=============================================
NEW models for the complete billing/receivable cycle. Kept in a dedicated module
(imported at the end of ``apps/billing/models.py``) so the sprint integrates as an
additive leaf without churning the recently-hardened core billing file.

* :class:`Package` / :class:`PackageItem` (S4-T1) — a contractual package: bundles
  N procedures (TUSS and/or CBHPM) for a fixed negotiated price, scoped to an
  :class:`~apps.billing.models.InsuranceProvider` / :class:`PriceTable`, with
  optional taxas / diárias / filme fields. :func:`resolve_package_price` resolves
  the price, using :meth:`apps.core.cbhpm_models.CBHPMItem.valor` (porte × valor_ch)
  when a line references CBHPM.

Cross-schema FK note: TUSSCode and CBHPMItem live in the PUBLIC schema; PostgreSQL
does not enforce referential integrity across schemas, so ``on_delete=PROTECT``
here is application-layer enforcement only — identical to
:class:`~apps.billing.models.PriceTableItem`.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

# ─── S4-T1: contractual packages ──────────────────────────────────────────────


class Package(models.Model):
    """A contractual package (pacote) negotiated with an operadora. Per-tenant.

    Bundles N procedures (TUSS and/or CBHPM) for a fixed negotiated price. When
    ``fixed_price`` is set (> 0) it IS the package price; otherwise the price is
    resolved by summing the itemised line values plus the optional
    taxa/diária/filme components (see :func:`resolve_package_price`).
    """

    name = models.CharField("Nome", max_length=200)
    provider = models.ForeignKey(
        "billing.InsuranceProvider", on_delete=models.PROTECT, related_name="packages"
    )
    price_table = models.ForeignKey(
        "billing.PriceTable",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="packages",
    )
    fixed_price = models.DecimalField(
        "Preço fixo negociado (R$)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(0)],
        help_text="Preço fechado do pacote. Vazio/0 = calcular pela soma dos itens + taxas.",
    )
    # Optional taxas / diárias / filme components of the bundle.
    taxa_value = models.DecimalField(
        "Taxas (R$)", max_digits=12, decimal_places=2, default=Decimal("0")
    )
    diaria_value = models.DecimalField(
        "Diárias (R$)", max_digits=12, decimal_places=2, default=Decimal("0")
    )
    filme_value = models.DecimalField(
        "Filme (R$)", max_digits=12, decimal_places=2, default=Decimal("0")
    )
    is_active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "billing"
        verbose_name = "Pacote"
        verbose_name_plural = "Pacotes"
        ordering = ["name"]

    def resolve_price(self) -> Decimal:
        """Convenience: delegate to :func:`resolve_package_price`."""
        return resolve_package_price(self)

    def __str__(self):
        return f"Pacote {self.name} ({self.provider.name})"


class PackageItem(models.Model):
    """A line in a :class:`Package`: one procedure (TUSS and/or CBHPM). Per-tenant.

    A line references a TUSS procedure, a CBHPM porte row, or both. ``unit_value``
    is an explicit per-unit override; when absent AND a CBHPM row is referenced,
    the line is valued via :meth:`CBHPMItem.valor` (porte × valor_ch).
    """

    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="items")
    # Cross-schema FK to public-schema TUSSCode — app-layer PROTECT only.
    tuss_code = models.ForeignKey(
        "core.TUSSCode",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="package_items",
    )
    # Cross-schema FK to public-schema CBHPMItem — app-layer PROTECT only.
    cbhpm = models.ForeignKey(
        "core.CBHPMItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="package_items",
    )
    description = models.CharField("Descrição", max_length=300, blank=True)
    quantity = models.DecimalField("Quantidade", max_digits=8, decimal_places=2, default=1)
    unit_value = models.DecimalField(
        "Valor unitário (R$)",
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Override explícito. Vazio + CBHPM → valora por porte (CBHPMItem.valor()).",
    )

    class Meta:
        app_label = "billing"
        verbose_name = "Item de Pacote"
        verbose_name_plural = "Itens de Pacote"

    def unit_price(self) -> Decimal:
        """Per-unit price: explicit override, else CBHPM porte valuation, else 0."""
        if self.unit_value is not None:
            return self.unit_value
        if self.cbhpm_id:
            return self.cbhpm.valor()  # type: ignore[union-attr]
        return Decimal("0")

    def line_value(self) -> Decimal:
        """Line total: ``unit_price × quantity`` (exact Decimal)."""
        qty = self.quantity if self.quantity is not None else Decimal("0")
        return self.unit_price() * qty

    def __str__(self):
        ref = (
            self.cbhpm.code
            if self.cbhpm_id
            else (self.tuss_code.code if self.tuss_code_id else "—")
        )
        return f"{ref} × {self.quantity} (Pacote {self.package_id})"


def resolve_package_price(package: Package) -> Decimal:
    """Resolve the price of a package.

    * If ``fixed_price`` is set (> 0), it IS the negotiated bundle price.
    * Otherwise: sum of each line's :meth:`PackageItem.line_value` (CBHPM lines
      valued via porte × valor_ch through :meth:`CBHPMItem.valor`) plus the
      optional taxa / diária / filme components.

    Pure Decimal arithmetic — never float.
    """
    if package.fixed_price and package.fixed_price > 0:
        return package.fixed_price
    items_total = sum((item.line_value() for item in package.items.all()), Decimal("0"))
    extras = (
        (package.taxa_value or Decimal("0"))
        + (package.diaria_value or Decimal("0"))
        + (package.filme_value or Decimal("0"))
    )
    return items_total + extras
