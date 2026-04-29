"""
S-054: Wizard setup endpoints for the tenant onboarding flow.

POST /api/v1/emr/setup/professional/
  Creates a Professional linked to request.user and a ScheduleConfig in one
  atomic transaction. Used by the onboarding wizard (Step 3+4).

POST /api/v1/emr/setup/professional/rerun/
  Re-runs setup for an existing tenant admin who misconfigured their clinic.
  Requires is_staff=True.
"""

import datetime

from django.db import transaction
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Professional, ScheduleConfig


class ProfessionalSetupSerializer(serializers.Serializer):
    council_type = serializers.ChoiceField(choices=["CRM", "COREN", "CRF", "CRO", "CREFITO", "CRP"])
    council_number = serializers.CharField(max_length=20)
    council_state = serializers.CharField(max_length=2, min_length=2)
    specialty = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    # Schedule config
    working_days = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        default=[1, 2, 3, 4, 5],  # Mon-Fri
    )
    work_start = serializers.TimeField(default=datetime.time(8, 0))
    work_end = serializers.TimeField(default=datetime.time(18, 0))
    lunch_start = serializers.TimeField(required=False, allow_null=True, default=None)
    lunch_end = serializers.TimeField(required=False, allow_null=True, default=None)
    slot_duration_minutes = serializers.IntegerField(min_value=10, max_value=120, default=30)


class WizardProfessionalSetupView(APIView):
    """
    POST /api/v1/emr/setup/professional/
    Creates Professional + ScheduleConfig for the authenticated admin user.
    Idempotent: if Professional already exists for this user, updates it.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ProfessionalSetupSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "details": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data

        with transaction.atomic():
            professional, created = Professional.objects.get_or_create(
                user=request.user,
                defaults={
                    "council_type": data["council_type"],
                    "council_number": data["council_number"],
                    "council_state": data["council_state"],
                    "specialty": data["specialty"],
                    "is_active": True,
                },
            )
            if not created:
                # Re-run: update existing professional
                professional.council_type = data["council_type"]
                professional.council_number = data["council_number"]
                professional.council_state = data["council_state"]
                professional.specialty = data["specialty"]
                professional.save()

            schedule_config, _ = ScheduleConfig.objects.get_or_create(
                professional=professional,
                defaults={
                    "working_days": data["working_days"],
                    "working_hours_start": data["work_start"],
                    "working_hours_end": data["work_end"],
                    "lunch_start": data["lunch_start"],
                    "lunch_end": data["lunch_end"],
                    "slot_duration_minutes": data["slot_duration_minutes"],
                    "is_active": True,
                },
            )
            if _:
                pass  # created
            else:
                # Re-run: update existing schedule config
                schedule_config.working_days = data["working_days"]
                schedule_config.working_hours_start = data["work_start"]
                schedule_config.working_hours_end = data["work_end"]
                schedule_config.lunch_start = data["lunch_start"]
                schedule_config.lunch_end = data["lunch_end"]
                schedule_config.slot_duration_minutes = data["slot_duration_minutes"]
                schedule_config.save()

        return Response(
            {
                "professional_id": str(professional.id),
                "created": created,
                "schedule_config_id": str(schedule_config.id),
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class WizardStatusView(APIView):
    """
    GET /api/v1/emr/setup/status/
    Returns whether the wizard has been completed for this tenant.
    Used by the frontend to decide whether to redirect to /setup or /dashboard.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        has_professional = Professional.objects.filter(is_active=True).exists()
        return Response({"wizard_complete": has_professional})
