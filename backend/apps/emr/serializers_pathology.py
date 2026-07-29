from rest_framework import serializers

from .models import PathologyReport, PathologySpecimen


class PathologySpecimenSerializer(serializers.ModelSerializer):
    class Meta:
        model = PathologySpecimen
        fields = "__all__"
        read_only_fields = ("id", "created_at")


class PathologyReportSerializer(serializers.ModelSerializer):
    specimens = PathologySpecimenSerializer(many=True, read_only=True)

    class Meta:
        model = PathologyReport
        fields = "__all__"
        read_only_fields = ("id", "created_by", "created_at", "updated_at")
