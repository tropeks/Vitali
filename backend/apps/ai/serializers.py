"""
AI app serializers — S-030, S-031, S-034
"""

from rest_framework import serializers

from .models import AIUsageLog, GlosaPrediction


class TUSSSuggestionSerializer(serializers.Serializer):
    tuss_code = serializers.CharField()
    description = serializers.CharField()
    rank = serializers.IntegerField()


VALID_GUIDE_TYPES = {"sadt", "sp_sadt", "consulta", "internacao", "odonto", ""}


class TUSSSuggestRequestSerializer(serializers.Serializer):
    description = serializers.CharField(min_length=3, max_length=500)
    guide_type = serializers.CharField(max_length=50, default="", allow_blank=True)

    def validate_guide_type(self, value):
        if value not in VALID_GUIDE_TYPES:
            raise serializers.ValidationError(
                f"guide_type must be one of: {', '.join(sorted(VALID_GUIDE_TYPES))}."
            )
        return value


class TUSSSuggestResponseSerializer(serializers.Serializer):
    suggestions = TUSSSuggestionSerializer(many=True)
    degraded = serializers.BooleanField()
    cached = serializers.BooleanField()


class TUSSSuggestFeedbackSerializer(serializers.Serializer):
    suggestion_id = serializers.UUIDField()
    accepted = serializers.BooleanField()


class AIUsageLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIUsageLog
        fields = [
            "id",
            "event_type",
            "tokens_in",
            "tokens_out",
            "latency_ms",
            "model",
            "created_at",
        ]
        read_only_fields = fields


# ─── Glosa Prediction (S-034) ─────────────────────────────────────────────────

VALID_GLOSA_GUIDE_TYPES = {"sadt", "sp_sadt", "consulta", "internacao", "odonto"}


class GlosaPredictRequestSerializer(serializers.Serializer):
    tuss_code = serializers.CharField(max_length=20)
    insurer_ans_code = serializers.RegexField(
        regex=r"^[0-9]{1,20}$",
        max_length=20,
        error_messages={"invalid": "insurer_ans_code must be 1-20 digits."},
    )
    insurer_name = serializers.CharField(max_length=200, allow_blank=True, default="")
    cid10_codes = serializers.ListField(
        child=serializers.CharField(max_length=10),
        allow_empty=True,
        max_length=20,
        default=list,
    )
    guide_type = serializers.ChoiceField(choices=list(VALID_GLOSA_GUIDE_TYPES))


class GlosaPredictResponseSerializer(serializers.Serializer):
    prediction_id = serializers.UUIDField(allow_null=True)
    risk_level = serializers.ChoiceField(choices=GlosaPrediction.RiskLevel.choices)
    risk_reason = serializers.CharField()
    risk_code = serializers.CharField(allow_blank=True)
    degraded = serializers.BooleanField()
    cached = serializers.BooleanField()
