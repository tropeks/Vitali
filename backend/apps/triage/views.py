"""REST views for the triage primitive."""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission, ModuleRequiredPermission

from .models import TriageSession
from .serializers import (
    TriageAnswerSerializer,
    TriageChiefComplaintSerializer,
    TriageQuestionSerializer,
    TriageSessionCreateSerializer,
    TriageSessionSerializer,
)
from .services.question_bank import RED_FLAG_QUESTIONS

_TRIAGE_MODULE = ModuleRequiredPermission("triage")


class QuestionBankView(APIView):
    """GET /api/v1/triage/questions/ — return the static question bank."""

    def get_permissions(self):
        return [IsAuthenticated(), _TRIAGE_MODULE, HasPermission("triage.read")]

    def get(self, request):
        return Response(TriageQuestionSerializer(RED_FLAG_QUESTIONS, many=True).data)


class SessionListCreateView(APIView):
    """GET / POST `/api/v1/triage/sessions/`."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [
                IsAuthenticated(),
                _TRIAGE_MODULE,
                HasPermission("triage.respond"),
            ]
        return [IsAuthenticated(), _TRIAGE_MODULE, HasPermission("triage.read")]

    def get(self, request):
        qs = TriageSession.objects.select_related("patient").all()
        status_q = request.query_params.get("status")
        urgency_q = request.query_params.get("urgency")
        if status_q:
            qs = qs.filter(status=status_q)
        if urgency_q:
            qs = qs.filter(urgency=urgency_q)
        return Response(TriageSessionSerializer(qs[:200], many=True).data)

    def post(self, request):
        serializer = TriageSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = serializer.save(created_by=request.user)
        return Response(TriageSessionSerializer(session).data, status=status.HTTP_201_CREATED)


class SessionDetailView(APIView):
    """GET `/api/v1/triage/sessions/{id}/`."""

    def get_permissions(self):
        return [IsAuthenticated(), _TRIAGE_MODULE, HasPermission("triage.read")]

    def get(self, request, session_id):
        session = self._fetch(session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(TriageSessionSerializer(session).data)

    @staticmethod
    def _fetch(session_id):
        try:
            return TriageSession.objects.select_related("patient").get(pk=session_id)
        except (TriageSession.DoesNotExist, ValueError):
            return None


class SessionChiefComplaintView(APIView):
    """PATCH `/api/v1/triage/sessions/{id}/complaint/`."""

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _TRIAGE_MODULE,
            HasPermission("triage.respond"),
        ]

    def patch(self, request, session_id):
        session = SessionDetailView._fetch(session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = TriageChiefComplaintSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session.record_chief_complaint(serializer.validated_data["chief_complaint"])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(TriageSessionSerializer(session).data)


class SessionAnswerView(APIView):
    """POST `/api/v1/triage/sessions/{id}/answer/`."""

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _TRIAGE_MODULE,
            HasPermission("triage.respond"),
        ]

    def post(self, request, session_id):
        session = SessionDetailView._fetch(session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = TriageAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session.answer(serializer.validated_data["key"], serializer.validated_data["value"])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(TriageSessionSerializer(session).data)


class SessionEvaluateView(APIView):
    """POST `/api/v1/triage/sessions/{id}/evaluate/`."""

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _TRIAGE_MODULE,
            HasPermission("triage.respond"),
        ]

    def post(self, request, session_id):
        session = SessionDetailView._fetch(session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            session.evaluate_now()
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(TriageSessionSerializer(session).data)


class SessionCompleteView(APIView):
    """POST `/api/v1/triage/sessions/{id}/complete/`."""

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _TRIAGE_MODULE,
            HasPermission("triage.respond"),
        ]

    def post(self, request, session_id):
        session = SessionDetailView._fetch(session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            session.complete()
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(TriageSessionSerializer(session).data)


class SessionCancelView(APIView):
    """POST `/api/v1/triage/sessions/{id}/cancel/`."""

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _TRIAGE_MODULE,
            HasPermission("triage.respond"),
        ]

    def post(self, request, session_id):
        session = SessionDetailView._fetch(session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            session.cancel()
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(TriageSessionSerializer(session).data)
