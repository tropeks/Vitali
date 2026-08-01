from django.db import transaction
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


# ─── nested write (LAB-3a): create the whole tree in one POST ─────────────────


class AntibiogramInputSerializer(serializers.Serializer):
    """One antibiogram entry inside an organism (write)."""

    antibiotic = serializers.CharField(max_length=120)
    method = serializers.CharField(max_length=60, required=False, allow_blank=True)
    mic_value = serializers.CharField(max_length=40, required=False, allow_blank=True)
    interpretation = serializers.ChoiceField(choices=AntibiogramEntry.Interpretation.choices)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True)


class OrganismInputSerializer(serializers.Serializer):
    """One isolated organism + its antibiogram (write)."""

    organism_name = serializers.CharField(max_length=160)
    colony_count = serializers.CharField(max_length=60, required=False, allow_blank=True)
    is_significant = serializers.BooleanField(required=False, default=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    antibiogram = AntibiogramInputSerializer(many=True, required=False)


class MicrobiologyResultSerializer(serializers.ModelSerializer):
    organisms = IsolatedOrganismSerializer(many=True, read_only=True)
    # Write-only tree input: the workspace posts culture + organisms[] +
    # antibiogram[] in a single request; the whole tree is created atomically.
    organisms_input = OrganismInputSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = MicrobiologyResult
        fields = "__all__"
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    @transaction.atomic
    def create(self, validated_data):
        organisms_data = validated_data.pop("organisms_input", [])
        result = MicrobiologyResult.objects.create(**validated_data)
        for org in organisms_data:
            abx_list = org.pop("antibiogram", [])
            organism = IsolatedOrganism.objects.create(result=result, **org)
            for abx in abx_list:
                AntibiogramEntry.objects.create(organism=organism, **abx)
        return result
