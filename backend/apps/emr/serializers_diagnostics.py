from rest_framework import serializers

from .models import CriticalLabResult, LabInstrument, LabSpecimen, LabSpecimenEvent


class LabInstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabInstrument
        fields = "__all__"
        read_only_fields = ("id", "last_seen_at", "created_at")


class LabSpecimenEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabSpecimenEvent
        fields = "__all__"
        read_only_fields = fields


class LabSpecimenSerializer(serializers.ModelSerializer):
    events = LabSpecimenEventSerializer(many=True, read_only=True)

    class Meta:
        model = LabSpecimen
        fields = "__all__"
        read_only_fields = (
            "id",
            "status",
            "current_location",
            "collected_at",
            "collected_by",
            "created_at",
        )


class CriticalLabResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = CriticalLabResult
        fields = "__all__"
        read_only_fields = fields
