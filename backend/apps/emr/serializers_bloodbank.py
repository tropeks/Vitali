"""
H1 — DRF serializers for the Banco de Sangue/Hemoterapia surface.

Two resources:
  * :class:`BloodComponentSerializer` — the SHARED governed hemocomponente
    catalog (``core.BloodComponentCatalog``), surfaced through the tenant-facing
    API and gated by ``hemoterapia.read`` / ``hemoterapia.manage``.
  * :class:`BloodBagSerializer` — the tenant blood bag (bolsa), with the
    governed ``component`` FK writable by pk plus a read-only
    ``component_display`` convenience and the derived ``available`` flag.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.core.blood_catalog_models import BloodComponentCatalog

from .bloodbank_models import BloodBag


class BloodComponentSerializer(serializers.ModelSerializer):
    """Read/write serializer for the SHARED hemocomponente catalog."""

    class Meta:
        model = BloodComponentCatalog
        fields = [
            "id",
            "code",
            "display",
            "system",
            "version",
            "active",
            "default_validade_dias",
            "context",
        ]
        read_only_fields = ["id", "system"]


class BloodBagSerializer(serializers.ModelSerializer):
    component_display = serializers.CharField(source="component.display", read_only=True)
    component_code = serializers.CharField(source="component.code", read_only=True)
    available = serializers.SerializerMethodField()

    class Meta:
        model = BloodBag
        fields = [
            "id",
            "identifier",
            "component",
            "component_code",
            "component_display",
            "abo",
            "rh_factor",
            "volume_ml",
            "collection_date",
            "expiry_date",
            "serology_status",
            "stock_status",
            "irradiada",
            "leucodepletada",
            "aferese",
            "lot",
            "available",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def get_available(self, obj) -> bool:
        return obj.is_available()
