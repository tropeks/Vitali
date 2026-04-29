"""
S-066: DRF views for waitlist management.

WaitlistViewSet:
  GET    /emr/waitlist/       — list entries (staff sees all, patients see own)
  POST   /emr/waitlist/       — create new entry
  DELETE /emr/waitlist/{id}/  — cancel entry (owner or staff only)
"""

import logging

from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.emr.models import Patient, Professional, WaitlistEntry

logger = logging.getLogger(__name__)

STATUS_BADGE_LABELS = {
    "waiting": "Aguardando",
    "notified": "Notificado — aguardando confirmação",
    "booked": "Agendado",
    "expired": "Expirado",
    "cancelled": "Cancelado",
}


# ─── Serializer ───────────────────────────────────────────────────────────────


class WaitlistEntrySerializer(serializers.ModelSerializer):
    status_display = serializers.SerializerMethodField()
    patient_name = serializers.SerializerMethodField()
    professional_name = serializers.SerializerMethodField()

    class Meta:
        model = WaitlistEntry
        fields = [
            "id",
            "patient",
            "patient_name",
            "professional",
            "professional_name",
            "preferred_date_from",
            "preferred_date_to",
            "preferred_time_start",
            "preferred_time_end",
            "status",
            "status_display",
            "notified_at",
            "expires_at",
            "offered_slot",
            "priority",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "notified_at",
            "expires_at",
            "offered_slot",
            "created_at",
            "patient_name",
            "professional_name",
        ]

    def get_status_display(self, obj):
        return STATUS_BADGE_LABELS.get(obj.status, obj.get_status_display())

    def get_patient_name(self, obj):
        try:
            return obj.patient.full_name
        except Exception:
            return None

    def get_professional_name(self, obj):
        try:
            return f"Dr(a). {obj.professional.user.full_name}"
        except Exception:
            return None


class WaitlistCreateSerializer(serializers.Serializer):
    professional_id = serializers.UUIDField()
    preferred_date_from = serializers.DateField()
    preferred_date_to = serializers.DateField()
    preferred_time_start = serializers.TimeField(required=False, allow_null=True)
    preferred_time_end = serializers.TimeField(required=False, allow_null=True)
    # Staff can specify patient_id; otherwise auto-set from request user
    patient_id = serializers.UUIDField(required=False, allow_null=True)
    priority = serializers.IntegerField(required=False, default=0, min_value=0)

    def validate(self, data):
        if data["preferred_date_from"] > data["preferred_date_to"]:
            raise serializers.ValidationError("preferred_date_from must be <= preferred_date_to")
        time_start = data.get("preferred_time_start")
        time_end = data.get("preferred_time_end")
        if time_start and time_end and time_start >= time_end:
            raise serializers.ValidationError(
                "preferred_time_start must be before preferred_time_end"
            )
        return data


# ─── Views ────────────────────────────────────────────────────────────────────


class WaitlistViewSet(APIView):
    """
    GET  /emr/waitlist/      — list entries
    POST /emr/waitlist/      — create entry
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        List waitlist entries.
        Staff (is_staff) can see all entries.
        Patient users see only their own entries.
        """
        if request.user.is_staff:
            qs = WaitlistEntry.objects.select_related("patient", "professional__user").all()
        else:
            # Try to find the Patient linked to this user
            try:
                patient = Patient.objects.get(user=request.user)
                qs = WaitlistEntry.objects.select_related("patient", "professional__user").filter(
                    patient=patient
                )
            except Patient.DoesNotExist:
                # Non-patient staff user — show nothing
                qs = WaitlistEntry.objects.none()

        serializer = WaitlistEntrySerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        """
        Create a new waitlist entry.
        If the user is a patient, auto-set patient from request.
        Staff can specify patient_id in the body.
        """
        serializer = WaitlistCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # Resolve patient
        patient = None
        patient_id = data.get("patient_id")
        if patient_id:
            if not request.user.is_staff:
                return Response(
                    {"error": "Apenas staff pode especificar patient_id."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            try:
                patient = Patient.objects.get(id=patient_id)
            except Patient.DoesNotExist:
                return Response(
                    {"error": "Paciente não encontrado."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            try:
                patient = Patient.objects.get(user=request.user)
            except Patient.DoesNotExist:
                return Response(
                    {"error": "Usuário não está vinculado a um paciente. Use patient_id."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Resolve professional
        try:
            professional = Professional.objects.get(id=data["professional_id"])
        except Professional.DoesNotExist:
            return Response(
                {"error": "Profissional não encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check for duplicate active entry
        existing = WaitlistEntry.objects.filter(
            patient=patient,
            professional=professional,
            status__in=["waiting", "notified"],
        ).first()
        if existing:
            return Response(
                {
                    "error": "Já existe uma entrada ativa na lista de espera para este profissional.",
                    "entry_id": str(existing.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        entry = WaitlistEntry.objects.create(
            patient=patient,
            professional=professional,
            preferred_date_from=data["preferred_date_from"],
            preferred_date_to=data["preferred_date_to"],
            preferred_time_start=data.get("preferred_time_start"),
            preferred_time_end=data.get("preferred_time_end"),
            priority=data.get("priority", 0),
            status="waiting",
        )

        logger.info(
            "WaitlistEntry %s created for patient %s / professional %s",
            entry.id,
            patient.id,
            professional.id,
        )

        return Response(
            WaitlistEntrySerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )


class WaitlistDetailView(APIView):
    """
    DELETE /emr/waitlist/{entry_id}/ — cancel entry (owner or staff only)
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, entry_id):
        try:
            entry = WaitlistEntry.objects.select_related("patient").get(id=entry_id)
        except WaitlistEntry.DoesNotExist:
            return Response(
                {"error": "Entrada na lista de espera não encontrada."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Authorization: staff only (Patient has no user FK)
        if not request.user.is_staff:
            return Response(
                {"error": "Sem permissão para cancelar esta entrada."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if entry.status in ("booked", "cancelled"):
            return Response(
                {
                    "error": f"Não é possível cancelar entrada com status '{entry.get_status_display()}'."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        entry.status = "cancelled"
        entry.save(update_fields=["status"])

        logger.info("WaitlistEntry %s cancelled by user %s", entry.id, request.user.id)

        return Response(
            {"message": "Entrada na lista de espera cancelada.", "id": str(entry.id)},
            status=status.HTTP_200_OK,
        )
