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

from .adt_models import Bed
from .emergency_models import EmergencyEncounter, RiskClassification
from .models import Professional, VitalSigns


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
            "disposition",
            "admission",
            "current_classification",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = (
            "id",
            "status",
            "disposition",
            "admission",
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


class StartAttendanceInputSerializer(serializers.Serializer):
    """Payload for ``start-attendance``: the (optional) profissional que assume."""

    professional = serializers.PrimaryKeyRelatedField(
        queryset=Professional.objects.all(), required=False, allow_null=True
    )


class CloseInputSerializer(serializers.Serializer):
    """Payload for ``close``: the ``disposition`` (+ internação bridge fields).

    When ``disposition == internacao`` and a ``bed`` is supplied, admitting +
    attending professional are required (adt.admit needs both) — the service then
    calls adt.admit inside the close transaction. Without a bed, the boletim closes
    as internação with a null admission (admite depois)."""

    disposition = serializers.ChoiceField(choices=EmergencyEncounter.Disposition.choices)
    bed = serializers.PrimaryKeyRelatedField(
        queryset=Bed.objects.all(), required=False, allow_null=True
    )
    admitting_professional = serializers.PrimaryKeyRelatedField(
        queryset=Professional.objects.all(), required=False, allow_null=True
    )
    attending_professional = serializers.PrimaryKeyRelatedField(
        queryset=Professional.objects.all(), required=False, allow_null=True
    )
    admission_source = serializers.CharField(required=False, allow_blank=True)
    admission_datetime = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        internacao = attrs.get("disposition") == EmergencyEncounter.Disposition.INTERNACAO
        if internacao and attrs.get("bed") is not None:
            missing = [
                field
                for field in ("admitting_professional", "attending_professional")
                if attrs.get(field) is None
            ]
            if missing:
                raise serializers.ValidationError(
                    {field: "Obrigatório ao internar com leito informado." for field in missing}
                )
        return attrs
