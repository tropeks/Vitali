"""
Telemedicine REST views — session list/create/read + state transitions.

State transitions are explicit endpoints (not PATCH on `status`) so the
audit trail is unambiguous: each transition writes its own request log
entry that downstream observability tools can attribute to a single user
action (CFM Res. 2.314/2022 §3 — start / end of every telemedicine session
must be logged).
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission, ModuleRequiredPermission

from .models import TelemedicineSession
from .serializers import (
    RecordingUrlSerializer,
    TelemedicineSessionCreateSerializer,
    TelemedicineSessionSerializer,
)

_TELEMED_MODULE = ModuleRequiredPermission("telemedicine")


class SessionListCreateView(APIView):
    """GET / POST `/api/v1/telemedicine/sessions/`."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [
                IsAuthenticated(),
                _TELEMED_MODULE,
                HasPermission("telemedicine.host"),
            ]
        return [
            IsAuthenticated(),
            _TELEMED_MODULE,
            HasPermission("telemedicine.read"),
        ]

    def get(self, request):
        qs = TelemedicineSession.objects.select_related("patient", "professional").all()
        patient = request.query_params.get("patient")
        professional = request.query_params.get("professional")
        status_q = request.query_params.get("status")
        if patient:
            qs = qs.filter(patient_id=patient)
        if professional:
            qs = qs.filter(professional_id=professional)
        if status_q:
            qs = qs.filter(status=status_q)
        return Response(TelemedicineSessionSerializer(qs[:200], many=True).data)

    def post(self, request):
        serializer = TelemedicineSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = serializer.save(created_by=request.user)
        return Response(
            TelemedicineSessionSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )


class SessionDetailView(APIView):
    """GET `/api/v1/telemedicine/sessions/{id}/`."""

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _TELEMED_MODULE,
            HasPermission("telemedicine.read"),
        ]

    def get(self, request, session_id):
        session = self._fetch(session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(TelemedicineSessionSerializer(session).data)

    @staticmethod
    def _fetch(session_id):
        try:
            return TelemedicineSession.objects.select_related("patient", "professional").get(
                pk=session_id
            )
        except (TelemedicineSession.DoesNotExist, ValueError):
            return None


class _BaseTransitionView(APIView):
    """Common skeleton for the start / complete / cancel endpoints."""

    transition_method: str = ""

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _TELEMED_MODULE,
            HasPermission("telemedicine.host"),
        ]

    def post(self, request, session_id):
        try:
            session = TelemedicineSession.objects.get(pk=session_id)
        except (TelemedicineSession.DoesNotExist, ValueError):
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            getattr(session, self.transition_method)()
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(TelemedicineSessionSerializer(session).data)


class SessionStartView(_BaseTransitionView):
    transition_method = "start"


class SessionCompleteView(_BaseTransitionView):
    transition_method = "complete"


class SessionCancelView(_BaseTransitionView):
    transition_method = "cancel"


class SessionRecordingView(APIView):
    """PATCH `/api/v1/telemedicine/sessions/{id}/recording/`."""

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _TELEMED_MODULE,
            HasPermission("telemedicine.host"),
        ]

    def patch(self, request, session_id):
        try:
            session = TelemedicineSession.objects.get(pk=session_id)
        except (TelemedicineSession.DoesNotExist, ValueError):
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = RecordingUrlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session.recording_url = serializer.validated_data["recording_url"]
        session.save(update_fields=["recording_url"])
        return Response(TelemedicineSessionSerializer(session).data)
