from rest_framework import serializers

from .models import LabIntegrationMessage


class LabIntegrationMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabIntegrationMessage
        fields = [
            "id",
            "source",
            "message_id",
            "direction",
            "format",
            "payload_hash",
            "canonical_payload",
            "status",
            "error",
            "lab_order",
            "applied_by",
            "applied_at",
            "created_at",
        ]
        read_only_fields = fields
