from rest_framework import serializers

from .models import ApprovalRequest, ApprovalStep


class ApprovalStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalStep
        fields = (
            "id",
            "sequence",
            "permission_required",
            "status",
            "decided_by",
            "decision_note",
            "decided_at",
        )


class ApprovalRequestSerializer(serializers.ModelSerializer):
    steps = ApprovalStepSerializer(many=True, read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = (
            "id",
            "workflow_key",
            "reference_type",
            "reference_id",
            "title",
            "context",
            "status",
            "requested_by",
            "created_at",
            "decided_at",
            "steps",
        )


class ApprovalDecisionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)
