from rest_framework import serializers

from .models import PathologyReport, PathologySpecimen


class PathologySpecimenSerializer(serializers.ModelSerializer):
    class Meta:
        model = PathologySpecimen
        fields = "__all__"
        read_only_fields = ("id", "created_at")


class PathologyReportSerializer(serializers.ModelSerializer):
    specimens = PathologySpecimenSerializer(many=True, read_only=True)
    # CID-O graváveis por código (roteados pelas properties do model, que
    # reconciliam topografia→core.CID10Code e morfologia→core.CIDOMorphology).
    cid_o_topography_code = serializers.CharField(required=False, allow_blank=True)
    cid_o_morphology_code = serializers.CharField(required=False, allow_blank=True)

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

    def create(self, validated_data):
        topo = validated_data.pop("cid_o_topography_code", None)
        morph = validated_data.pop("cid_o_morphology_code", None)
        instance = super().create(validated_data)
        return self._apply_cido(
            instance,
            {"cid_o_topography_code": topo, "cid_o_morphology_code": morph},
        )

    def update(self, instance, validated_data):
        topo = validated_data.pop("cid_o_topography_code", None)
        morph = validated_data.pop("cid_o_morphology_code", None)
        instance = super().update(instance, validated_data)
        return self._apply_cido(
            instance,
            {"cid_o_topography_code": topo, "cid_o_morphology_code": morph},
        )
