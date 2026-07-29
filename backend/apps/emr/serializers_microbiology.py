from rest_framework import serializers

from .models import AntibiogramEntry, IsolatedOrganism, MicrobiologyResult


class AntibiogramEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AntibiogramEntry
        fields = "__all__"
        read_only_fields = ("id", "created_at")


class IsolatedOrganismSerializer(serializers.ModelSerializer):
    antibiogram = AntibiogramEntrySerializer(many=True, read_only=True)

    class Meta:
        model = IsolatedOrganism
        fields = "__all__"
        read_only_fields = ("id", "created_at")


class MicrobiologyResultSerializer(serializers.ModelSerializer):
    organisms = IsolatedOrganismSerializer(many=True, read_only=True)

    class Meta:
        model = MicrobiologyResult
        fields = "__all__"
        read_only_fields = ("id", "created_by", "created_at", "updated_at")
