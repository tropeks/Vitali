"""
Manchester triage catalog serializers (Sprint E1)
=================================================
Read/write serializers for the SHARED governed Manchester catalog —
``ManchesterFlowchart`` (fluxograma) and ``ManchesterDiscriminator``
(discriminador). Surfaced through the tenant-facing API and gated by the
``emergency.read`` / ``emergency.manage`` role permissions (see
``apps.core.views_manchester``). The catalog lives in the public schema; write
verbs are governance operations, not per-tenant clinical data.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.core.manchester_catalog_models import (
    ManchesterDiscriminator,
    ManchesterFlowchart,
    acuity_target_minutes,
)


class ManchesterFlowchartSerializer(serializers.ModelSerializer):
    class Meta:
        model = ManchesterFlowchart
        fields = ["id", "code", "display", "system", "version", "active"]
        read_only_fields = ["id", "system"]


class ManchesterDiscriminatorSerializer(serializers.ModelSerializer):
    target_minutes = serializers.SerializerMethodField()

    class Meta:
        model = ManchesterDiscriminator
        fields = [
            "id",
            "flowchart",
            "code",
            "name",
            "description",
            "acuity_level",
            "target_minutes",
            "is_general",
            "active",
        ]
        read_only_fields = ["id", "target_minutes"]

    def get_target_minutes(self, obj) -> int:
        return acuity_target_minutes(obj.acuity_level)
