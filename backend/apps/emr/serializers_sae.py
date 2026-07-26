"""
N2-T3 — DRF serializers for the executable SAE domain (apps.emr.sae_models).

One serializer per resource in the SAE chain (diagnóstico → planejamento →
intervenção → prescrição → evolução). Governed catalog FKs are writable by pk;
each exposes a read-only ``*_code`` convenience mirroring the model's
backward-compatible accessor. ``patient`` / ``created_by`` are server-assigned
(never client-set) — the viewset derives ``patient`` from the encounter and
stamps ``created_by`` from the request user.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import (
    NursingCareplan,
    NursingCareplanIntervention,
    NursingDiagnosis,
    NursingEvolution,
    NursingPrescriptionItem,
)


class NursingDiagnosisSerializer(serializers.ModelSerializer):
    nanda_code = serializers.CharField(read_only=True)

    class Meta:
        model = NursingDiagnosis
        fields = [
            "id",
            "patient",
            "encounter",
            "nanda",
            "nanda_code",
            "legacy_nanda_text",
            "nanda_unmatched",
            "related_factors",
            "defining_characteristics",
            "status",
            "priority",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = (
            "id",
            "patient",
            "legacy_nanda_text",
            "nanda_unmatched",
            "created_by",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        encounter = attrs.get("encounter", getattr(self.instance, "encounter", None))
        if encounter is None:
            raise serializers.ValidationError({"encounter": "Atendimento obrigatório."})
        return attrs


class NursingCareplanSerializer(serializers.ModelSerializer):
    noc_code = serializers.CharField(read_only=True)

    class Meta:
        model = NursingCareplan
        fields = [
            "id",
            "diagnosis",
            "noc",
            "noc_code",
            "legacy_noc_text",
            "noc_unmatched",
            "expected_outcome",
            "target",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = (
            "id",
            "legacy_noc_text",
            "noc_unmatched",
            "created_by",
            "created_at",
            "updated_at",
        )


class NursingCareplanInterventionSerializer(serializers.ModelSerializer):
    nic_code = serializers.CharField(read_only=True)

    class Meta:
        model = NursingCareplanIntervention
        fields = [
            "id",
            "careplan",
            "nic",
            "nic_code",
            "legacy_nic_text",
            "nic_unmatched",
            "notes",
            "created_at",
        ]
        read_only_fields = ("id", "legacy_nic_text", "nic_unmatched", "created_at")


class NursingPrescriptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = NursingPrescriptionItem
        fields = [
            "id",
            "intervention",
            "description",
            "frequency_hours",
            "start_at",
            "active",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    def validate_frequency_hours(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError("frequency_hours deve ser um número de horas > 0.")
        return value


class NursingEvolutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = NursingEvolution
        fields = [
            "id",
            "patient",
            "encounter",
            "text",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "patient", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        encounter = attrs.get("encounter", getattr(self.instance, "encounter", None))
        if encounter is None:
            raise serializers.ValidationError({"encounter": "Atendimento obrigatório."})
        return attrs
