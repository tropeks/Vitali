from rest_framework import serializers

from apps.emr.models import LabOrder, LabOrderItem


class PortalLabItemSerializer(serializers.ModelSerializer):
    abnormal_flag_display = serializers.CharField(source="get_abnormal_flag_display")

    class Meta:
        model = LabOrderItem
        fields = [
            "id",
            "test_name",
            "category",
            "method",
            "specimen_type",
            "unit",
            "reference_range",
            "result_value",
            "result_data",
            "microbiology",
            "abnormal_flag",
            "abnormal_flag_display",
            "result_notes",
            "validated_at",
        ]
        read_only_fields = fields


class PortalLabOrderSerializer(serializers.ModelSerializer):
    items = PortalLabItemSerializer(many=True)
    report_url = serializers.SerializerMethodField()

    class Meta:
        model = LabOrder
        fields = [
            "id",
            "accession_number",
            "requested_at",
            "completed_at",
            "clinical_indication",
            "items",
            "report_url",
        ]
        read_only_fields = fields

    def get_report_url(self, obj):
        return f"/portal/me/lab-results/{obj.id}/report/"
