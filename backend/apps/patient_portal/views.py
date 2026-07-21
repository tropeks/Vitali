"""
Patient portal REST views.

Two surfaces:

1. **Admin surface** (`/portal/access/...`) — clinic staff mint, list, and
   revoke portal access for patients. Gated by `patient_portal` module +
   `users.write` (admin-level permission).

2. **Self-data surface** (`/portal/me/...`) — a portal user authenticated
   via the JWT obtained after consuming their invite token can read only
   their own patient data. Each endpoint resolves
   `request.user.patient_portal_access` → that user's `Patient` and filters
   the queryset to it.

The self-data permission `portal.self_access` is a marker permission — the
user's `Role.permissions` must contain it, and the views *additionally*
verify that the portal access record is `active`. This double check stops
a clinic staff user (who happens to have `portal.self_access` in their
role) from poking the `/portal/me/` endpoints.
"""

from __future__ import annotations

from django.http import HttpResponse
from django.template.loader import render_to_string
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditLog
from apps.core.permissions import HasPermission, ModuleRequiredPermission
from apps.emr.models import Allergy, Appointment, Encounter, Prescription

from .models import PatientPortalAccess
from .services import deliver_portal_invite
from .serializers import (
    PatientPortalAccessCreateSerializer,
    PatientPortalAccessSerializer,
    PortalAllergySerializer,
    PortalAppointmentSerializer,
    PortalEncounterSerializer,
    PortalPatientSerializer,
    PortalPrescriptionSerializer,
)

_PORTAL_MODULE = ModuleRequiredPermission("patient_portal")


class IsPortalSelfAccess(BasePermission):
    """
    Permission guard for `/portal/me/*` endpoints.

    Requires:
    - Authenticated user.
    - User has the `portal.self_access` permission in their Role.
    - There is a `PatientPortalAccess` row linking the user to a Patient AND
      its status is `active` (not `invited` / `revoked`).
    """

    message = "Portal self-access not granted for this user."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        role = getattr(user, "role", None)
        if not role or "portal.self_access" not in role.permissions:
            return False
        access = getattr(user, "patient_portal_access", None)
        return access is not None and access.status == PatientPortalAccess.STATUS_ACTIVE


# ─── Admin surface ───────────────────────────────────────────────────────────


class AccessListCreateView(APIView):
    """GET / POST `/api/v1/portal/access/` — clinic staff manage invites."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [
                IsAuthenticated(),
                _PORTAL_MODULE,
                HasPermission("users.write"),
            ]
        return [
            IsAuthenticated(),
            _PORTAL_MODULE,
            HasPermission("users.read"),
        ]

    def get(self, request):
        qs = PatientPortalAccess.objects.select_related("patient", "user").all()
        status_q = request.query_params.get("status")
        if status_q:
            qs = qs.filter(status=status_q)
        return Response(PatientPortalAccessSerializer(qs[:200], many=True).data)

    def post(self, request):
        serializer = PatientPortalAccessCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        access = serializer.save(created_by=request.user)
        # Fire the activation link to the patient (WhatsApp → email fallback).
        # Fail-open: delivery problems never fail invite creation.
        deliver_portal_invite(access)
        return Response(
            PatientPortalAccessSerializer(access).data,
            status=status.HTTP_201_CREATED,
        )


class AccessDetailView(APIView):
    """GET `/api/v1/portal/access/{id}/`."""

    def get_permissions(self):
        return [IsAuthenticated(), _PORTAL_MODULE, HasPermission("users.read")]

    def get(self, request, access_id):
        try:
            access = PatientPortalAccess.objects.select_related("patient", "user").get(pk=access_id)
        except (PatientPortalAccess.DoesNotExist, ValueError):
            return Response(
                {"detail": "Portal access not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(PatientPortalAccessSerializer(access).data)


class AccessRevokeView(APIView):
    """POST `/api/v1/portal/access/{id}/revoke/`."""

    def get_permissions(self):
        return [
            IsAuthenticated(),
            _PORTAL_MODULE,
            HasPermission("users.write"),
        ]

    def post(self, request, access_id):
        try:
            access = PatientPortalAccess.objects.get(pk=access_id)
        except (PatientPortalAccess.DoesNotExist, ValueError):
            return Response(
                {"detail": "Portal access not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        access.revoke()
        return Response(PatientPortalAccessSerializer(access).data)


class AccessActivateView(APIView):
    """
    POST `/api/v1/portal/access/activate/` — consume an invite token.

    Public-ish (still requires auth on the user account just created); the
    typical flow is the patient receives the invite, signs into the user
    account that was provisioned for them, then POSTs the token. Once
    consumed the link goes `invited → active`.
    """

    def get_permissions(self):
        return [IsAuthenticated()]

    def post(self, request):
        token = request.data.get("invite_token") or ""
        try:
            access = PatientPortalAccess.objects.get(invite_token=token)
        except PatientPortalAccess.DoesNotExist:
            return Response(
                {"detail": "Invalid invite token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if access.user_id != request.user.id:
            return Response(
                {"detail": "Invite belongs to another user."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            access.activate()
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(PatientPortalAccessSerializer(access).data)


# ─── Self-data surface ───────────────────────────────────────────────────────


class _SelfView(APIView):
    """Common skeleton for /portal/me/* endpoints."""

    def get_permissions(self):
        return [IsAuthenticated(), _PORTAL_MODULE, IsPortalSelfAccess()]

    def _patient(self, request):
        access = request.user.patient_portal_access
        access.touch()
        return access.patient


class MeView(_SelfView):
    def get(self, request):
        return Response(PortalPatientSerializer(self._patient(request)).data)


class MeAppointmentsView(_SelfView):
    def get(self, request):
        patient = self._patient(request)
        qs = Appointment.objects.filter(patient=patient).order_by("-start_time")[:100]
        return Response(PortalAppointmentSerializer(qs, many=True).data)


class MeEncountersView(_SelfView):
    def get(self, request):
        patient = self._patient(request)
        # Patients only see signed encounters — draft / cancelled clinical
        # records are not portal-visible.
        qs = Encounter.objects.filter(patient=patient, status="signed").order_by("-encounter_date")[
            :100
        ]
        return Response(PortalEncounterSerializer(qs, many=True).data)


class MePrescriptionsView(_SelfView):
    def get(self, request):
        patient = self._patient(request)
        qs = Prescription.objects.filter(
            patient=patient,
            status__in=["signed", "partially_dispensed", "dispensed"],
        ).order_by("-created_at")[:100]
        return Response(PortalPrescriptionSerializer(qs, many=True).data)


class MeAllergiesView(_SelfView):
    def get(self, request):
        patient = self._patient(request)
        qs = Allergy.objects.filter(patient=patient).order_by("-created_at")
        return Response(PortalAllergySerializer(qs, many=True).data)


class MeExportView(_SelfView):
    def get(self, request):
        patient = self._patient(request)
        export_format = request.query_params.get("export_format", "json")

        patient_data = PortalPatientSerializer(patient).data
        appointments = PortalAppointmentSerializer(
            Appointment.objects.filter(patient=patient).order_by("-start_time")[:100], many=True
        ).data
        encounters = PortalEncounterSerializer(
            Encounter.objects.filter(patient=patient, status="signed").order_by("-encounter_date")[
                :100
            ],
            many=True,
        ).data
        prescriptions = PortalPrescriptionSerializer(
            Prescription.objects.filter(
                patient=patient, status__in=["signed", "partially_dispensed", "dispensed"]
            ).order_by("-created_at")[:100],
            many=True,
        ).data
        allergies = PortalAllergySerializer(
            Allergy.objects.filter(patient=patient).order_by("-created_at"), many=True
        ).data

        data = {
            "patient": patient_data,
            "appointments": appointments,
            "encounters": encounters,
            "prescriptions": prescriptions,
            "allergies": allergies,
        }

        if export_format == "json":
            return Response(data)
        elif export_format == "pdf":
            html_string = render_to_string("patient_portal/export.html", {"data": data})
            try:
                from weasyprint import HTML

                pdf_bytes = HTML(string=html_string).write_pdf()
                response = HttpResponse(pdf_bytes, content_type="application/pdf")
                response["Content-Disposition"] = (
                    f'attachment; filename="patient_export_{patient.id}.pdf"'
                )
                return response
            except ImportError:
                return Response(
                    {"detail": "Gerador de PDF indisponível."},
                    status=status.HTTP_501_NOT_IMPLEMENTED,
                )
        else:
            return Response({"detail": "Formato inválido."}, status=status.HTTP_400_BAD_REQUEST)


class MeDeletionRequestView(_SelfView):
    def post(self, request):
        patient = self._patient(request)
        reason = request.data.get("reason", "")

        AuditLog.objects.create(
            user=request.user,
            action="patient_deletion_requested",
            resource_type="Patient",
            resource_id=str(patient.id),
            old_data={},
            new_data={
                "reason": reason,
                "note": "Retenção legal de 20 anos se aplica. Nenhuma exclusão física realizada.",
            },
        )
        return Response(
            {
                "detail": "Solicitação registrada com sucesso. A retenção legal de 20 anos se aplica."
            },
            status=status.HTTP_200_OK,
        )
