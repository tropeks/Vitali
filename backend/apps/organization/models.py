"""Tenant-scoped organizational master data."""

import uuid

from django.core.exceptions import ValidationError
from django.db import models


class OrganizationalRecord(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        INACTIVE = "inactive", "Inativo"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField("Código", max_length=50, unique=True)
    name = models.CharField("Nome", max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ("name",)

    def __str__(self):
        return f"{self.code} — {self.name}"


class LegalEntity(OrganizationalRecord):
    """Company or other legal entity operated by this tenant."""

    legal_name = models.CharField("Razão social", max_length=255, blank=True, default="")
    tax_identifier = models.CharField(
        "Identificador fiscal", max_length=32, blank=True, default="", db_index=True
    )

    class Meta(OrganizationalRecord.Meta):
        verbose_name = "Entidade legal"
        verbose_name_plural = "Entidades legais"


class Facility(OrganizationalRecord):
    """Physical establishment (hospital, clinic, laboratory or warehouse)."""

    legal_entity = models.ForeignKey(
        LegalEntity, on_delete=models.PROTECT, related_name="facilities"
    )

    # ── M2-S1-T3: governed FK to the SHARED CNES catalog ──────────────────────
    # PostgreSQL does not enforce FK integrity across schemas (tenant → public),
    # so — like emr.Professional.cnes — we use DO_NOTHING and rely on the
    # protect_cnes_establishment_deletion pre_delete signal (apps/core/signals.py)
    # to block deleting a CNES establishment that any tenant references. The
    # legacy free-text column preserves any raw/unmatched CNES number (never lose
    # data), exposed via the ``cnes_code`` accessor for symmetry with Professional.
    cnes = models.ForeignKey(
        "core.CNESEstablishment",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Estabelecimento CNES",
    )
    legacy_cnes_text = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Código CNES bruto não reconciliado com core.CNESEstablishment.",
    )
    cnes_unmatched = models.BooleanField(
        default=False,
        help_text="True quando legacy_cnes_text não corresponde a nenhum CNESEstablishment governado.",
    )

    class Meta(OrganizationalRecord.Meta):
        verbose_name = "Estabelecimento"
        verbose_name_plural = "Estabelecimentos"

    @property
    def cnes_code(self) -> str:
        """CNES code string: the governed FK's code when linked, else raw legacy text."""
        if self.cnes_id:
            return self.cnes.code  # type: ignore[union-attr]
        return self.legacy_cnes_text

    @cnes_code.setter
    def cnes_code(self, value: str) -> None:
        code = (value or "").strip()
        if not code:
            self.cnes = None
            self.legacy_cnes_text = ""
            self.cnes_unmatched = False
            return
        from apps.core.models import CNESEstablishment

        match = CNESEstablishment.objects.filter(code=code).first()
        if match is not None:
            self.cnes = match
            self.legacy_cnes_text = ""
            self.cnes_unmatched = False
        else:
            self.cnes = None
            self.legacy_cnes_text = code
            self.cnes_unmatched = True


class OrganizationalUnit(OrganizationalRecord):
    """Hierarchical department, service, ward or administrative unit."""

    facility = models.ForeignKey(Facility, on_delete=models.PROTECT, related_name="units")
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, related_name="children", null=True, blank=True
    )

    class Meta(OrganizationalRecord.Meta):
        verbose_name = "Unidade organizacional"
        verbose_name_plural = "Unidades organizacionais"

    def clean(self):
        super().clean()
        if self.parent_id:
            if self.parent_id == self.id:
                raise ValidationError({"parent": "Uma unidade não pode ser pai de si mesma."})
            if self.parent.facility_id != self.facility_id:
                raise ValidationError(
                    {"parent": "A unidade pai deve pertencer ao mesmo estabelecimento."}
                )
            ancestor = self.parent
            visited = {self.id}
            while ancestor is not None:
                if ancestor.id in visited:
                    raise ValidationError({"parent": "A hierarquia não pode conter ciclos."})
                visited.add(ancestor.id)
                ancestor = ancestor.parent


class CostCenter(OrganizationalRecord):
    """Hierarchical accounting responsibility center."""

    legal_entity = models.ForeignKey(
        LegalEntity, on_delete=models.PROTECT, related_name="cost_centers"
    )
    facility = models.ForeignKey(
        Facility,
        on_delete=models.PROTECT,
        related_name="cost_centers",
        null=True,
        blank=True,
        help_text="Vazio para centros corporativos.",
    )
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, related_name="children", null=True, blank=True
    )

    class Meta(OrganizationalRecord.Meta):
        verbose_name = "Centro de custo"
        verbose_name_plural = "Centros de custo"

    def clean(self):
        super().clean()
        if self.facility_id and self.facility.legal_entity_id != self.legal_entity_id:
            raise ValidationError(
                {"facility": "O estabelecimento deve pertencer à mesma entidade legal."}
            )
        if self.parent_id:
            if self.parent_id == self.id:
                raise ValidationError(
                    {"parent": "Um centro de custo não pode ser pai de si mesmo."}
                )
            if self.parent.legal_entity_id != self.legal_entity_id:
                raise ValidationError(
                    {"parent": "O centro pai deve pertencer à mesma entidade legal."}
                )
            ancestor = self.parent
            visited = {self.id}
            while ancestor is not None:
                if ancestor.id in visited:
                    raise ValidationError({"parent": "A hierarquia não pode conter ciclos."})
                visited.add(ancestor.id)
                ancestor = ancestor.parent
