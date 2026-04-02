"""
Vitali — Analytics Serializers (S-035)
Explicit DRF serializers for billing analytics endpoints.
Defined here for future OpenAPI/Swagger generation support.
"""
from rest_framework import serializers


class BillingOverviewSerializer(serializers.Serializer):
    period = serializers.CharField()
    total_billed = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_collected = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_denied = serializers.DecimalField(max_digits=14, decimal_places=2)
    denial_rate = serializers.FloatField()
    guides_total = serializers.IntegerField()
    guides_submitted = serializers.IntegerField()
    guides_paid = serializers.IntegerField()
    guides_denied = serializers.IntegerField()
    guides_draft_pending = serializers.IntegerField()


class MonthlyRevenueBucketSerializer(serializers.Serializer):
    period = serializers.CharField()
    billed = serializers.DecimalField(max_digits=14, decimal_places=2)
    collected = serializers.DecimalField(max_digits=14, decimal_places=2)
    denied = serializers.DecimalField(max_digits=14, decimal_places=2)


class DenialByInsurerSerializer(serializers.Serializer):
    insurer_name = serializers.CharField()
    ans_code = serializers.CharField()
    total_guides = serializers.IntegerField()
    denied_guides = serializers.IntegerField()
    denial_rate = serializers.FloatField()
    denied_value = serializers.DecimalField(max_digits=14, decimal_places=2)


class BatchThroughputBucketSerializer(serializers.Serializer):
    period = serializers.CharField()
    created_count = serializers.IntegerField()
    closed_count = serializers.IntegerField()


class GlosaAccuracyRowSerializer(serializers.Serializer):
    insurer_ans_code = serializers.CharField()
    insurer_name = serializers.CharField()
    total_predictions = serializers.IntegerField()
    predicted_high = serializers.IntegerField()
    was_denied = serializers.IntegerField()
    true_positives = serializers.IntegerField()
    precision = serializers.FloatField(allow_null=True)
    recall = serializers.FloatField(allow_null=True)
