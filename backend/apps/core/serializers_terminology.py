"""
Terminology catalog admin serializers (Sprint A1-T2 / T3)
=========================================================
Read serializers for the SHARED governed terminology catalogs — CBO, CNES,
LOINC, UCUM — surfaced through the platform-admin API so a Vitali operator can
list/paginate each catalog and inspect import status. The catalogs live in the
public schema; these serializers are read-only projections (imports happen via
the dedicated trigger endpoint / management commands, never a plain writable
serializer).
"""

from __future__ import annotations

from rest_framework import serializers

from apps.core.cbo_cnes_models import CBOCode, CNESEstablishment
from apps.core.loinc_models import LoincCode, UcumUnit

_COMMON_FIELDS = ["id", "code", "display", "system", "version", "active"]


class CBOCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CBOCode
        fields = [*_COMMON_FIELDS, "family"]
        read_only_fields = fields


class CNESEstablishmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CNESEstablishment
        fields = [*_COMMON_FIELDS, "establishment_type", "municipality_ibge"]
        read_only_fields = fields


class LoincCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoincCode
        fields = [*_COMMON_FIELDS, "component", "property", "loinc_system"]
        read_only_fields = fields


class UcumUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = UcumUnit
        fields = _COMMON_FIELDS
        read_only_fields = _COMMON_FIELDS


class CatalogImportStatusSerializer(serializers.Serializer):
    """Per-system import-status summary line (row count + last import run)."""

    system = serializers.CharField()
    row_count = serializers.IntegerField()
    last_import_at = serializers.DateTimeField(allow_null=True)
    last_import_status = serializers.CharField(allow_null=True)
    last_import_version = serializers.CharField(allow_null=True, allow_blank=True)
