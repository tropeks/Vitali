"""
C1 — DRF serializers for the Centro Cirúrgico structure (apps.emr.surgery_models).

One serializer per resource: sala cirúrgica → caso cirúrgico → procedimento
(TUSS). ``created_by`` is server-set (read-only); ``surgeon`` / ``patient`` are
client-set. ``SurgicalProcedure`` exposes a read-only ``tuss_code_value``
(null-safe TUSS code string) alongside the writable ``tuss_code`` FK.
"""

from __future__ import annotations

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from .models import (
    AnestheticEvent,
    AnestheticRecord,
    OperatingRoom,
    PacuAssessment,
    PacuRecord,
    SurgicalCase,
    SurgicalChecklist,
    SurgicalMaterial,
    SurgicalProcedure,
    SurgicalTeamMember,
    SurgicalTime,
)


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


class SurgicalCaseScheduleSerializer(serializers.Serializer):
    """Input for ``POST /surgical-cases/{id}/schedule/``: room + time window."""

    operating_room = serializers.PrimaryKeyRelatedField(queryset=OperatingRoom.objects.all())
    scheduled_start = serializers.DateTimeField()
    scheduled_end = serializers.DateTimeField()


class SurgicalCaseRescheduleSerializer(serializers.Serializer):
    """Input for ``POST /surgical-cases/{id}/reschedule/``: new window, optional
    new room (omit to keep the case's current room)."""

    operating_room = serializers.PrimaryKeyRelatedField(
        queryset=OperatingRoom.objects.all(), required=False, allow_null=True
    )
    scheduled_start = serializers.DateTimeField()
    scheduled_end = serializers.DateTimeField()


class SurgicalCaseCancelSerializer(serializers.Serializer):
    """Input for ``POST /surgical-cases/{id}/cancel/``: optional reason."""

    reason = serializers.CharField(required=False, allow_blank=True, default="")


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


# ─── C3: equipe + tempos (append-only) + checklist OMS ────────────────────────


class SurgicalTeamMemberSerializer(serializers.ModelSerializer):
    """Team member of a case. Writable CRUD; a duplicate ``(case, professional,
    role)`` is rejected with 400 (UniqueTogetherValidator + DB constraint)."""

    professional_name = serializers.CharField(source="professional.user.full_name", read_only=True)

    class Meta:
        model = SurgicalTeamMember
        fields = [
            "id",
            "case",
            "professional",
            "professional_name",
            "role",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "professional_name", "created_at", "updated_at")
        validators = [
            UniqueTogetherValidator(
                queryset=SurgicalTeamMember.objects.all(),
                fields=["case", "professional", "role"],
                message="Este profissional já ocupa essa função no caso.",
            )
        ]


class SurgicalTimeSerializer(serializers.ModelSerializer):
    """Read-only representation of an intra-op time. Appended via the
    ``record-time`` action, never through this serializer."""

    class Meta:
        model = SurgicalTime
        fields = [
            "id",
            "case",
            "event",
            "recorded_at",
            "recorded_by",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


class SurgicalChecklistSerializer(serializers.ModelSerializer):
    """Read-only representation of a confirmed safe-surgery checklist phase.
    Confirmed via the ``checklist`` action, never through this serializer."""

    class Meta:
        model = SurgicalChecklist
        fields = [
            "id",
            "case",
            "phase",
            "items",
            "confirmed_at",
            "confirmed_by",
            "created_at",
        ]
        read_only_fields = fields


class SurgicalCaseRecordTimeSerializer(serializers.Serializer):
    """Input for ``POST /surgical-cases/{id}/record-time/``."""

    event = serializers.ChoiceField(choices=SurgicalTime.Event.choices)
    recorded_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class SurgicalCaseChecklistSerializer(serializers.Serializer):
    """Input for ``POST /surgical-cases/{id}/checklist/``."""

    phase = serializers.ChoiceField(choices=SurgicalChecklist.Phase.choices)
    items = serializers.JSONField(required=False, default=dict)


# ─── C6: OPME / materiais + consumo de sala ───────────────────────────────────


class SurgicalMaterialSerializer(serializers.ModelSerializer):
    """Material / OPME planejado + consumido de um caso. ``quantity_consumed`` é
    read-only (avançado só pela ação ``consume`` via o serviço); ``created_by`` é
    definido no servidor."""

    class Meta:
        model = SurgicalMaterial
        fields = [
            "id",
            "case",
            "kind",
            "stock_item",
            "description",
            "quantity_planned",
            "quantity_consumed",
            "laterality",
            "lot",
            "serial",
            "manufacturer",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = (
            "id",
            "quantity_consumed",
            "created_by",
            "created_at",
            "updated_at",
        )


class SurgicalMaterialConsumeSerializer(serializers.Serializer):
    """Input for ``POST /surgical-materials/{id}/consume/``: units consumed."""

    quantity = serializers.IntegerField(min_value=1)


# ─── CC2: ficha anestésica + timeline do ato anestésico ───────────────────────


class AnestheticEventSerializer(serializers.ModelSerializer):
    """An entry on the anesthetic timeline (droga / vital / evento / ventilação).
    ``recorded_by`` is server-set from ``request.user`` in the viewset."""

    class Meta:
        model = AnestheticEvent
        fields = [
            "id",
            "record",
            "timestamp",
            "kind",
            "description",
            "dose",
            "value",
            "recorded_by",
            "created_at",
        ]
        read_only_fields = ("id", "recorded_by", "created_at")


class AnestheticRecordSerializer(serializers.ModelSerializer):
    """Ficha anestésica de um caso (OneToOne). ``events`` são read-only aninhados
    (adicionados via o ``AnestheticEventViewSet``); ``created_by`` é definido no
    servidor. Uma 2ª ficha para o mesmo caso é rejeitada com 400."""

    events = AnestheticEventSerializer(many=True, read_only=True)

    class Meta:
        model = AnestheticRecord
        fields = [
            "id",
            "case",
            "anesthesiologist",
            "technique",
            "asa_classification",
            "anesthesia_start",
            "anesthesia_end",
            "notes",
            "events",
            "created_by",
            "created_at",
            "updated_at",
        ]
        # ``case`` is a OneToOneField → DRF auto-adds a UniqueValidator, so a 2nd
        # ficha for the same case is rejected with 400.
        read_only_fields = ("id", "events", "created_by", "created_at", "updated_at")


# ─── CS2: SRPA / PACU — recuperação pós-anestésica ────────────────────────────


class PacuAssessmentSerializer(serializers.ModelSerializer):
    """Uma avaliação periódica (Aldrete) na timeline da SRPA. ``recorded_by`` é o
    profissional que avaliou (client-set: enfermeiro/anestesista da SRPA)."""

    class Meta:
        model = PacuAssessment
        fields = [
            "id",
            "record",
            "assessed_at",
            "aldrete_score",
            "consciousness",
            "respiration",
            "circulation",
            "activity",
            "oxygen",
            "pain_score",
            "notes",
            "recorded_by",
            "created_at",
        ]
        read_only_fields = ("id", "created_at")


class PacuRecordSerializer(serializers.ModelSerializer):
    """Registro de SRPA de um caso (OneToOne). ``assessments`` são read-only
    aninhados (adicionados via o ``PacuAssessmentViewSet``); ``created_by`` é
    definido no servidor. Um 2º registro para o mesmo caso é rejeitado com 400."""

    assessments = PacuAssessmentSerializer(many=True, read_only=True)

    class Meta:
        model = PacuRecord
        fields = [
            "id",
            "case",
            "admitted_at",
            "admitted_by",
            "aldrete_admission",
            "aldrete_discharge",
            "discharged_at",
            "discharge_destination",
            "discharge_criteria_met",
            "notes",
            "assessments",
            "created_by",
            "created_at",
            "updated_at",
        ]
        # ``case`` is a OneToOneField → DRF auto-adds a UniqueValidator, so a 2nd
        # registro for the same case is rejected with 400.
        read_only_fields = ("id", "assessments", "created_by", "created_at", "updated_at")
