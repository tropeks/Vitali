"""Patient-safe serializers for diagnostic imaging studies."""

from urllib.parse import quote

from rest_framework import serializers

from apps.core.imaging_bridge import DicomStudy


class PortalImagingStudySerializer(serializers.ModelSerializer):
    series_count = serializers.IntegerField(source="number_of_series", read_only=True)
    instance_count = serializers.IntegerField(source="number_of_instances", read_only=True)
    available = serializers.BooleanField(source="has_pixel_data", read_only=True)
    viewer_url = serializers.SerializerMethodField()
    report_url = serializers.SerializerMethodField()

    class Meta:
        model = DicomStudy
        fields = [
            "id",
            "accession_number",
            "study_instance_uid",
            "modality",
            "body_part_examined",
            "description",
            "study_date",
            "series_count",
            "instance_count",
            "available",
            "viewer_url",
            "report_url",
        ]

    def get_viewer_url(self, obj):
        if not obj.has_pixel_data:
            return None
        uid = quote(obj.study_instance_uid, safe=".")
        return f"/visualizador/viewer?StudyInstanceUIDs={uid}"

    def get_report_url(self, obj):
        report = obj.report_document
        if report is None or not report.is_signed:
            return None
        return f"/api/v1/portal/me/imaging-studies/{obj.id}/report/"


class PortalImagingReportSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    doc_type = serializers.CharField()
    content = serializers.CharField()
    signed_at = serializers.DateTimeField()
    signed_by_name = serializers.CharField(source="signed_by.full_name", allow_null=True)
    signature_hash = serializers.CharField()
    is_icp_brasil = serializers.BooleanField()
