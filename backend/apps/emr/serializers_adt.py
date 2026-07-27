"""
L1 — DRF serializers for the ADT/Leitos bed structure (apps.emr.adt_models).

One serializer per resource in the physical hierarchy (unidade → quarto →
leito). The governed ``BedType`` catalog FK on ``Bed`` is writable by pk, and a
writable ``bed_type_code`` (routed through the model's property setter, which
resolves the code to a governed FK else marks the row unmatched) mirrors the SAE
``_CatalogCodeWriteMixin`` — the terminology picker exposes only code/display,
so the workspace posts ``bed_type_code``. ``Bed.unit`` is server-derived from the
room (never client-set) to keep the denormalized FK consistent.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import Admission, AdmissionEvent, Bed, InpatientUnit, Room


class _CatalogCodeWriteMixin(serializers.ModelSerializer):
    """Make a governed ``*_code`` field writable by routing it through the model's
    property setter, which resolves the code to a governed FK (or marks the row
    unmatched + stores the legacy text) — the same reconcile-safe shape as
    ``cbo``/``cnes``/``nanda``.

    ``ModelSerializer.create`` can't hand a *property* kwarg to ``Model.__init__``
    (it only accepts real fields), so we pop the code and apply it via ``setattr``
    after the instance exists. An explicit FK pk, if ever sent, wins over the code.
    """

    #: subclasses set the ("<x>_code", "<x>") pair.
    catalog_code_field: str = ""
    catalog_fk_field: str = ""

    def create(self, validated_data):
        code = validated_data.pop(self.catalog_code_field, None)
        fk_provided = self.catalog_fk_field in validated_data
        instance = super().create(validated_data)
        if code is not None and not fk_provided:
            setattr(instance, self.catalog_code_field, code)
            instance.save()
        return instance

    def update(self, instance, validated_data):
        code = validated_data.pop(self.catalog_code_field, None)
        fk_provided = self.catalog_fk_field in validated_data
        instance = super().update(instance, validated_data)
        if code is not None and not fk_provided:
            setattr(instance, self.catalog_code_field, code)
            instance.save()
        return instance


class InpatientUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = InpatientUnit
        fields = [
            "id",
            "facility",
            "name",
            "code",
            "active",
            "default_bed_type",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_at", "updated_at")


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = [
            "id",
            "unit",
            "name",
            "gender",
            "isolation",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_at", "updated_at")


class BedSerializer(_CatalogCodeWriteMixin):
    bed_type_code = serializers.CharField(required=False, allow_blank=True)
    catalog_code_field = "bed_type_code"
    catalog_fk_field = "bed_type"

    class Meta:
        model = Bed
        fields = [
            "id",
            "room",
            "unit",
            "identifier",
            "status",
            "bed_type",
            "bed_type_code",
            "legacy_bed_type_text",
            "bed_type_unmatched",
            "active",
            "created_at",
            "updated_at",
        ]
        # ``unit`` is derived from the room in the viewset (denormalized FK kept
        # consistent server-side, never client-set).
        read_only_fields = (
            "id",
            "unit",
            "legacy_bed_type_text",
            "bed_type_unmatched",
            "created_at",
            "updated_at",
        )


# ─── L2: admissão/internação ─────────────────────────────────────────────────


class AdmissionSerializer(serializers.ModelSerializer):
    """Admission (internação). ``bed`` is a write-only input consumed by the
    service on create (it drives the bed-occupancy transition); the persisted
    ``current_bed`` is read-only. Lifecycle fields (status/disposition/discharge
    datetime) are set by the service, never client-posted."""

    # Client posts ``bed`` to admit; the viewset routes it through the service,
    # which sets ``current_bed``. Not a model field on write → write_only source.
    bed = serializers.PrimaryKeyRelatedField(
        queryset=Bed.objects.all(), write_only=True, required=True
    )

    class Meta:
        model = Admission
        fields = [
            "id",
            "patient",
            "admitting_professional",
            "attending_professional",
            "bed",
            "current_bed",
            "encounter",
            "admission_source",
            "admission_datetime",
            "expected_discharge_datetime",
            "actual_discharge_datetime",
            "disposition",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = (
            "id",
            "current_bed",
            "actual_discharge_datetime",
            "disposition",
            "status",
            "created_at",
            "updated_at",
        )


class AdmissionDischargeSerializer(serializers.Serializer):
    """Payload for the ``discharge`` action."""

    disposition = serializers.ChoiceField(choices=Admission.Disposition.choices)
    actual_discharge_datetime = serializers.DateTimeField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True)


class AdmissionEventSerializer(serializers.ModelSerializer):
    """Read-only append-only ADT event."""

    class Meta:
        model = AdmissionEvent
        fields = [
            "id",
            "admission",
            "event_type",
            "from_bed",
            "to_bed",
            "actor",
            "reason",
            "created_at",
        ]
        read_only_fields = fields
