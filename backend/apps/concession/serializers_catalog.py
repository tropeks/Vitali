"""B0-T1 — serializer for the ConcessionService catalog."""

from rest_framework import serializers

from .models import ConcessionService


class ConcessionServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConcessionService
        fields = [
            "id",
            "code",
            "name",
            "modality",
            "tuss_code",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
