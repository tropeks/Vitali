"""
C1 — DRF serializers for the Centro Cirúrgico structure (apps.emr.surgery_models).

One serializer per resource: sala cirúrgica → caso cirúrgico → procedimento
(TUSS). ``created_by`` is server-set (read-only); ``surgeon`` / ``patient`` are
client-set. ``SurgicalProcedure`` exposes a read-only ``tuss_code_value``
(null-safe TUSS code string) alongside the writable ``tuss_code`` FK.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import OperatingRoom, SurgicalCase, SurgicalProcedure


class OperatingRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperatingRoom
        fields = [
            "id",
            "facility",
            "code",
            "name",
            "room_type",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_at", "updated_at")


class SurgicalCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurgicalCase
        fields = [
            "id",
            "patient",
            "encounter",
            "admission",
            "surgeon",
            "operating_room",
            "scheduled_start",
            "scheduled_end",
            "priority",
            "status",
            "anesthesia_type",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
        ]
        # ``created_by`` is server-set from request.user in the viewset.
        read_only_fields = ("id", "created_by", "created_at", "updated_at")


class SurgicalProcedureSerializer(serializers.ModelSerializer):
    tuss_code_value = serializers.CharField(read_only=True)

    class Meta:
        model = SurgicalProcedure
        fields = [
            "id",
            "case",
            "tuss_code",
            "tuss_code_value",
            "quantity",
            "laterality",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "tuss_code_value", "created_at", "updated_at")
