"""
E2 — DRF serializers for the PS/Emergência domain (apps.emr.emergency_models).

``EmergencyEncounterSerializer`` is the boletim CRUD surface; ``status`` and
``created_by`` are server-managed (status is driven by the classify service /
E3 transitions, created_by is stamped from request.user). It embeds the
read-only ``current_classification`` (latest triagem) so the workspace has the
patient's priority in one round-trip. ``ClassifyInputSerializer`` is the
``classify`` action payload. ``RiskClassificationSerializer`` is the read-only
append-only history.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.core.manchester_catalog_models import ManchesterDiscriminator

from .emergency_models import EmergencyEncounter, RiskClassification
from .models import VitalSigns


class RiskClassificationSerializer(serializers.ModelSerializer):
    """Read-only append-only risk classification (triagem)."""

    flowchart_code = serializers.CharField(read_only=True)
    discriminator_code = serializers.CharField(read_only=True)

    class Meta:
        model = RiskClassification
        fields = [
            "id",
            "boletim",
            "flowchart",
            "flowchart_code",
            "discriminator",
            "discriminator_code",
            "acuity_level",
            "target_minutes",
            "vitals",
            "classified_by",
            "classified_at",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


class EmergencyEncounterSerializer(serializers.ModelSerializer):
    """Boletim de atendimento de emergência (BAE). ``status``/``created_by`` are
    server-managed; ``current_classification`` embeds the latest triagem."""

    current_classification = RiskClassificationSerializer(read_only=True)

    class Meta:
        model = EmergencyEncounter
        fields = [
            "id",
            "patient",
            "encounter",
            "arrival_at",
            "mode_of_arrival",
            "chief_complaint",
            "status",
            "current_classification",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = (
            "id",
            "status",
            "current_classification",
            "created_by",
            "created_at",
            "updated_at",
        )


class ClassifyInputSerializer(serializers.Serializer):
    """Payload for the ``classify`` action: a Manchester discriminator (+ optional
    vitals snapshot + notes). The service copies acuity/target from the catalog."""

    discriminator = serializers.PrimaryKeyRelatedField(
        queryset=ManchesterDiscriminator.objects.all()
    )
    vitals = serializers.PrimaryKeyRelatedField(
        queryset=VitalSigns.objects.all(), required=False, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)
