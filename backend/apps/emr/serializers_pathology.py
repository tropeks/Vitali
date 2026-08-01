from django.db import transaction
from rest_framework import serializers

from .models import PathologyReport, PathologySpecimen


class PathologySpecimenSerializer(serializers.ModelSerializer):
    class Meta:
        model = PathologySpecimen
        fields = "__all__"
        read_only_fields = ("id", "created_at")


class SpecimenInputSerializer(serializers.Serializer):
    """One specimen inside a pathology report (write)."""

    # ``label`` shadows Field.label (DRF internal) — safe at runtime, mypy noise.
    label = serializers.CharField(max_length=60)  # type: ignore[assignment]
    description = serializers.CharField(required=False, allow_blank=True)
    site = serializers.CharField(max_length=160, required=False, allow_blank=True)
    blocks_count = serializers.IntegerField(required=False, default=0, min_value=0)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True)


class PathologyReportSerializer(serializers.ModelSerializer):
    specimens = PathologySpecimenSerializer(many=True, read_only=True)
    # CID-O graváveis por código (roteados pelas properties do model, que
    # reconciliam topografia→core.CID10Code e morfologia→core.CIDOMorphology).
    cid_o_topography_code = serializers.CharField(required=False, allow_blank=True)
    cid_o_morphology_code = serializers.CharField(required=False, allow_blank=True)
    # Write-only tree input: post report + specimens[] in one request.
    specimens_input = SpecimenInputSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = PathologyReport
        fields = "__all__"
        # FK/texto legado/unmatched são derivados da reconciliação, nunca client-set.
        read_only_fields = (
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "cid_o_topography",
            "cid_o_topography_cid10",
            "cid_o_topography_unmatched",
            "cid_o_morphology",
            "cid_o_morphology_ref",
            "cid_o_morphology_unmatched",
        )

    def _apply_cido(self, instance, validated_data):
        topo = validated_data.pop("cid_o_topography_code", None)
        morph = validated_data.pop("cid_o_morphology_code", None)
        changed = []
        if topo is not None:
            instance.cid_o_topography_code = topo
            changed += ["cid_o_topography", "cid_o_topography_cid10", "cid_o_topography_unmatched"]
        if morph is not None:
            instance.cid_o_morphology_code = morph
            changed += ["cid_o_morphology", "cid_o_morphology_ref", "cid_o_morphology_unmatched"]
        if changed:
            instance.save(update_fields=changed)
        return instance

    @transaction.atomic
    def create(self, validated_data):
        topo = validated_data.pop("cid_o_topography_code", None)
        morph = validated_data.pop("cid_o_morphology_code", None)
        specimens = validated_data.pop("specimens_input", [])
        instance = super().create(validated_data)
        self._apply_cido(
            instance,
            {"cid_o_topography_code": topo, "cid_o_morphology_code": morph},
        )
        for spec in specimens:
            PathologySpecimen.objects.create(report=instance, **spec)
        return instance

    def update(self, instance, validated_data):
        topo = validated_data.pop("cid_o_topography_code", None)
        morph = validated_data.pop("cid_o_morphology_code", None)
        validated_data.pop("specimens_input", None)  # specimens editados via endpoint próprio
        instance = super().update(instance, validated_data)
        return self._apply_cido(
            instance,
            {"cid_o_topography_code": topo, "cid_o_morphology_code": morph},
        )
