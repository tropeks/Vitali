"""
AI app views — S-030, S-031
"""
import logging
from datetime import date

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission

from . import services
from .models import AIUsageLog, TUSSAISuggestion
from .serializers import (
    AIUsageLogSerializer,
    TUSSSuggestFeedbackSerializer,
    TUSSSuggestRequestSerializer,
    TUSSSuggestResponseSerializer,
)

logger = logging.getLogger(__name__)


class TUSSSuggestView(APIView):
    """
    POST /api/v1/ai/tuss-suggest/
    Returns up to 3 TUSS code suggestions for a procedure description.
    Requires FEATURE_AI_TUSS=True and ai.use permission.
    """
    def get_permissions(self):
        return [IsAuthenticated(), HasPermission('ai.use')]

    def post(self, request):
        if not getattr(settings, 'FEATURE_AI_TUSS', False):
            return Response({"detail": "AI TUSS coding feature is not enabled."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TUSSSuggestRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        description = serializer.validated_data['description']
        guide_type = serializer.validated_data.get('guide_type', '')
        tenant_schema = request.tenant.schema_name

        result = services.suggest(description, guide_type, tenant_schema)

        response_data = {
            'suggestions': [
                {
                    'tuss_code': s.tuss_code,
                    'description': s.description,
                    'rank': s.rank,
                    'tuss_code_id': s.tuss_code_id,
                    'suggestion_id': s.suggestion_id,
                }
                for s in result.suggestions
            ],
            'degraded': result.degraded,
            'cached': result.cached,
        }
        return Response(response_data)


class TUSSSuggestFeedbackView(APIView):
    """
    POST /api/v1/ai/tuss-suggest/feedback/
    Records whether the faturista accepted or rejected a suggestion.
    Ownership check: suggestion must belong to this tenant (Decision 19).
    """
    def get_permissions(self):
        return [IsAuthenticated(), HasPermission('ai.use')]

    def post(self, request):
        if not getattr(settings, 'FEATURE_AI_TUSS', False):
            return Response({"detail": "AI TUSS coding feature is not enabled."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TUSSSuggestFeedbackSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        suggestion_id = serializer.validated_data['suggestion_id']
        accepted = serializer.validated_data['accepted']

        # Cross-tenant ownership guard: only suggestions created in this tenant schema.
        # TUSSAISuggestion lives in the tenant schema, so tenant isolation is automatic —
        # but we still do an explicit lookup to ensure 404 on wrong-tenant IDs.
        try:
            suggestion = TUSSAISuggestion.objects.get(id=suggestion_id)
        except TUSSAISuggestion.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        suggestion.accepted = accepted
        suggestion.feedback_at = timezone.now()
        suggestion.save(update_fields=['accepted', 'feedback_at'])

        return Response({"status": "ok"})


class AIUsageView(APIView):
    """
    GET /api/v1/ai/usage/
    Monthly usage summary. Admin only.
    """
    def get_permissions(self):
        return [IsAuthenticated(), HasPermission('users.read')]

    def get(self, request):
        # Default to current month
        try:
            year = int(request.query_params.get('year', date.today().year))
            month = int(request.query_params.get('month', date.today().month))
        except (ValueError, TypeError):
            return Response({"detail": "year and month must be integers."}, status=status.HTTP_400_BAD_REQUEST)

        logs = AIUsageLog.objects.filter(
            created_at__year=year,
            created_at__month=month,
        )
        totals = logs.aggregate(
            total_calls=Count('id'),
            total_tokens_in=Sum('tokens_in'),
            total_tokens_out=Sum('tokens_out'),
            total_latency_ms=Sum('latency_ms'),
        )

        # Acceptance rate
        suggestions = TUSSAISuggestion.objects.filter(
            created_at__year=year,
            created_at__month=month,
        )
        total_suggestions = suggestions.count()
        accepted_suggestions = suggestions.filter(accepted=True).count()

        return Response({
            'year': year,
            'month': month,
            'llm_calls': totals['total_calls'] or 0,
            'tokens_in': totals['total_tokens_in'] or 0,
            'tokens_out': totals['total_tokens_out'] or 0,
            'total_latency_ms': totals['total_latency_ms'] or 0,
            'suggestions_shown': total_suggestions,
            'suggestions_accepted': accepted_suggestions,
            'acceptance_rate': round(accepted_suggestions / total_suggestions, 3) if total_suggestions else None,
        })
