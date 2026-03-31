"""
AI app serializers — S-030, S-031
"""
from rest_framework import serializers

from .models import AIUsageLog, TUSSAISuggestion


class TUSSSuggestionSerializer(serializers.Serializer):
    tuss_code = serializers.CharField()
    description = serializers.CharField()
    rank = serializers.IntegerField()


VALID_GUIDE_TYPES = {'sadt', 'sp_sadt', 'consulta', 'internacao', 'odonto', ''}


class TUSSSuggestRequestSerializer(serializers.Serializer):
    description = serializers.CharField(min_length=3, max_length=500)
    guide_type = serializers.CharField(max_length=50, default='', allow_blank=True)

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
        fields = ['id', 'event_type', 'tokens_in', 'tokens_out', 'latency_ms', 'model', 'created_at']
        read_only_fields = fields
