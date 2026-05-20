"""REST views for the smart scheduling slot ranker."""

from __future__ import annotations

from datetime import date, timedelta

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission, ModuleRequiredPermission
from apps.emr.models import Patient, Professional

from .services.ranker import suggest_slots

_SMART_MODULE = ModuleRequiredPermission("smart_scheduling")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class SuggestSlotsView(APIView):
    """
    GET /api/v1/scheduling/suggest/?professional=…&patient=…&from=…&to=…&limit=…

    Returns up to `limit` ranked candidate slots for the professional in the
    `[from, to]` window. `patient` is optional; when present it sharpens the
    `patient_history` signal.
    """

    DEFAULT_LIMIT = 5
    MAX_LIMIT = 50
    DEFAULT_WINDOW_DAYS = 14
    MAX_WINDOW_DAYS = 60

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _SMART_MODULE,
            HasPermission("smart_scheduling.read"),
        ]

    def get(self, request):
        professional_id = request.query_params.get("professional")
        if not professional_id:
            return Response(
                {"detail": "`professional` query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            professional = Professional.objects.select_related("schedule_config").get(
                pk=professional_id
            )
        except (Professional.DoesNotExist, ValueError):
            return Response({"detail": "Professional not found."}, status=status.HTTP_404_NOT_FOUND)

        patient = None
        patient_id = request.query_params.get("patient")
        if patient_id:
            try:
                patient = Patient.objects.get(pk=patient_id)
            except (Patient.DoesNotExist, ValueError):
                return Response({"detail": "Patient not found."}, status=status.HTTP_404_NOT_FOUND)

        from_date = _parse_date(request.query_params.get("from")) or date.today()
        to_date = _parse_date(request.query_params.get("to")) or (
            from_date + timedelta(days=self.DEFAULT_WINDOW_DAYS - 1)
        )
        if to_date < from_date:
            return Response(
                {"detail": "`to` must be on or after `from`."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if (to_date - from_date).days > self.MAX_WINDOW_DAYS:
            return Response(
                {
                    "detail": (
                        f"Window too wide; capped at {self.MAX_WINDOW_DAYS} days "
                        "to keep response time predictable."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            limit = min(
                int(request.query_params.get("limit", self.DEFAULT_LIMIT)),
                self.MAX_LIMIT,
            )
        except (TypeError, ValueError):
            limit = self.DEFAULT_LIMIT
        if limit < 1:
            limit = self.DEFAULT_LIMIT

        slots = suggest_slots(
            professional=professional,
            patient=patient,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
        )
        return Response(
            {
                "professional_id": str(professional.pk),
                "patient_id": str(patient.pk) if patient else None,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "suggestions": [slot.to_dict() for slot in slots],
            }
        )
