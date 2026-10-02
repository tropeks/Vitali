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

import logging

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.mixins import AuditReadAPIViewMixin
from apps.core.models import AuditLog
from apps.core.permissions import HasPermission, IsPortalSelfAccess, ModuleRequiredPermission
from apps.emr.models import Allergy, Appointment, Encounter, Prescription

from .models import PatientPortalAccess, PortalConsent
from .serializers import (
    PatientPortalAccessCreateSerializer,
    PatientPortalAccessSerializer,
    PatientPortalInviteSerializer,
    PatientRepresentativeSerializer,
    PortalAllergySerializer,
    PortalAppointmentSerializer,
    PortalConsentSerializer,
    PortalEncounterSerializer,
    PortalPatientSerializer,
    PortalPrescriptionSerializer,
)
from .services import deliver_portal_invite

logger = logging.getLogger(__name__)

_PORTAL_MODULE = ModuleRequiredPermission("patient_portal")

# `IsPortalSelfAccess` mudou para `apps.core.permissions` (ordem 036) para que
# `apps.emr` (lista de espera) reuse o mesmo guard sem importar
# `apps.patient_portal` — o contrato `domain-independence` do import-linter
# proíbe essa aresta. Reexportado aqui para não quebrar quem importa deste
# módulo.


# ─── Admin surface ───────────────────────────────────────────────────────────


class AccessListCreateView(AuditReadAPIViewMixin, APIView):
    """GET / POST `/api/v1/portal/access/` — clinic staff manage invites."""

    audit_resource_type = "PatientPortalAccess"
    AUDIT_LIST_PARAMS: tuple[str, ...] = ("status",)

    def _alvo_da_busca(self, criteria: dict[str, str]) -> str:
        # `?status=` é filtro, não id: vai para `new_data`, nunca para `resource_id`.
        return ""

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
            PatientPortalInviteSerializer(access).data,
            status=status.HTTP_201_CREATED,
        )


class AccessDetailView(AuditReadAPIViewMixin, APIView):
    """GET `/api/v1/portal/access/{id}/`."""

    audit_resource_type = "PatientPortalAccess"
    AUDIT_LOOKUP_KWARG = "access_id"

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


class AccessResendView(APIView):
    """POST `/api/v1/portal/access/{id}/resend/` — new invite token, same record (order 039)."""

    def get_permissions(self):
        return [IsAuthenticated(), _PORTAL_MODULE, HasPermission("users.write")]

    def post(self, request, access_id):
        try:
            access = PatientPortalAccess.objects.get(pk=access_id)
        except (PatientPortalAccess.DoesNotExist, ValueError):
            return Response(
                {"detail": "Portal access not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            access.reissue_invite()
        except ValueError:
            return Response(
                {"detail": "Only an invited access can be re-sent."},
                status=status.HTTP_409_CONFLICT,
            )
        # The token itself never goes to the trail: only who re-sent and until when.
        AuditLog.objects.create(
            user=request.user,
            action="portal_invite_resent",
            resource_type="PatientPortalAccess",
            resource_id=str(access.pk),
            new_data={"invite_expires_at": access.invite_expires_at.isoformat()},
        )
        # Fail-open, like the creation: a delivery problem never fails the re-send.
        try:
            deliver_portal_invite(access)
        except Exception:  # noqa: BLE001 — o token novo já está salvo e vai na resposta
            logger.exception("portal: falha ao entregar o convite reenviado %s", access.pk)
        return Response(PatientPortalInviteSerializer(access).data)


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
            access = PatientPortalAccess.find_by_invite_token(token)
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


class _SelfLeitura(AuditReadAPIViewMixin, _SelfView):
    """``_SelfView`` que deixa trilha de leitura (ordem 030).

    Quem lê é o próprio titular, e ler o próprio prontuário continua sendo
    operação de tratamento a registrar (LGPD art. 37) — o export, sobretudo, é
    a cópia mais ampla do prontuário que sai do sistema. O alvo em
    ``resource_id`` é o paciente do titular, para ``/audit-trail/?patient=``
    achar a leitura; os ``AUDIT_LIST_PARAMS`` de cada view (ex.
    ``export_format``) vão para ``new_data``. As ``_SelfView`` que não leem
    prontuário, ou que já gravam trilha própria, continuam em ``_SelfView`` e
    estão classificadas na guarda.
    """

    def _alvo_da_busca(self, criteria: dict[str, str]) -> str:
        access = getattr(self.request.user, "patient_portal_access", None)
        return str(access.patient_id) if access is not None else ""


class MeView(_SelfLeitura):
    audit_resource_type = "PortalProfile"
    AUDIT_LIST_PARAMS: tuple[str, ...] = ()

    def get(self, request):
        return Response(PortalPatientSerializer(self._patient(request)).data)


class MeRepresentativesView(_SelfLeitura):
    audit_resource_type = "PortalRepresentatives"
    AUDIT_LIST_PARAMS: tuple[str, ...] = ()

    def get(self, request):
        patient = self._patient(request)
        return Response(
            PatientRepresentativeSerializer(
                patient.portal_representatives.filter(active=True), many=True
            ).data
        )


class MeConsentsView(_SelfLeitura):
    audit_resource_type = "PortalConsents"
    AUDIT_LIST_PARAMS: tuple[str, ...] = ()

    def get(self, request):
        return Response(
            PortalConsentSerializer(
                self._patient(request).portal_consents.order_by("-granted_at"), many=True
            ).data
        )

    def post(self, request):
        serializer = PortalConsentSerializer(
            data={**request.data, "patient": self._patient(request).pk}
        )
        serializer.is_valid(raise_exception=True)
        consent = serializer.save(granted_by=request.user)
        AuditLog.objects.create(
            user=request.user,
            action="portal_consent_granted",
            resource_type="portalconsent",
            resource_id=str(consent.pk),
            new_data={"purpose": consent.purpose, "policy_version": consent.policy_version},
        )
        return Response(PortalConsentSerializer(consent).data, status=201)


class MeConsentRevokeView(_SelfView):
    def post(self, request, consent_id):
        try:
            consent = PortalConsent.objects.get(pk=consent_id, patient=self._patient(request))
        except PortalConsent.DoesNotExist:
            return Response({"detail": "Consent not found."}, status=404)
        consent.revoked_at = timezone.now()
        consent.save(update_fields=["revoked_at"])
        AuditLog.objects.create(
            user=request.user,
            action="portal_consent_revoked",
            resource_type="portalconsent",
            resource_id=str(consent.pk),
        )
        return Response(PortalConsentSerializer(consent).data)


class MeAppointmentsView(_SelfLeitura):
    audit_resource_type = "PortalAppointments"
    AUDIT_LIST_PARAMS: tuple[str, ...] = ()

    def get(self, request):
        patient = self._patient(request)
        qs = Appointment.objects.filter(patient=patient).order_by("-start_time")[:100]
        return Response(PortalAppointmentSerializer(qs, many=True).data)


class MeEncountersView(_SelfLeitura):
    audit_resource_type = "PortalEncounters"
    AUDIT_LIST_PARAMS: tuple[str, ...] = ()

    def get(self, request):
        patient = self._patient(request)
        # Patients only see signed encounters — draft / cancelled clinical
        # records are not portal-visible.
        qs = Encounter.objects.filter(patient=patient, status="signed").order_by("-encounter_date")[
            :100
        ]
        return Response(PortalEncounterSerializer(qs, many=True).data)


class MePrescriptionsView(_SelfLeitura):
    audit_resource_type = "PortalPrescriptions"
    AUDIT_LIST_PARAMS: tuple[str, ...] = ()

    def get(self, request):
        patient = self._patient(request)
        qs = Prescription.objects.filter(
            patient=patient,
            status__in=["signed", "partially_dispensed", "dispensed"],
        ).order_by("-created_at")[:100]
        return Response(PortalPrescriptionSerializer(qs, many=True).data)


class MeAllergiesView(_SelfLeitura):
    audit_resource_type = "PortalAllergies"
    AUDIT_LIST_PARAMS: tuple[str, ...] = ()

    def get(self, request):
        patient = self._patient(request)
        qs = Allergy.objects.filter(patient=patient).order_by("-created_at")
        return Response(PortalAllergySerializer(qs, many=True).data)


class MeExportView(_SelfLeitura):
    audit_resource_type = "PortalExport"
    AUDIT_LIST_PARAMS: tuple[str, ...] = ("export_format",)

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
