"""
Sprint M1-S5 — Portal transacional REST views.

Three self-service surfaces layered on the existing ``/portal/me/*`` skeleton
(``_SelfView`` resolves ``request.user`` → the authenticated patient and blocks
cross-patient access):

* **Scheduling** (S5-T1): list availability (reusing ``whatsapp.slot_service``),
  book / reschedule / cancel — booking availability enforced by the emr
  ``AppointmentSchedulingService`` (no slot logic duplicated here).
* **PIX payment** (S5-T2): list the patient's *own* open receivables and raise a
  ``billing.PIXCharge`` for one (reusing ``AsaasService``).
* **Pre-consult forms** (S5-T3): fetch the ``ClinicalFormTemplate`` assigned to
  an upcoming appointment and submit an (encrypted) ``ClinicalFormResponse``.

Every write is LGPD-consent-checked against ``PortalConsent`` and audited.

── Cross-app coupling (for the parent to reconcile with import-linter + S4) ──
This module imports two sibling domain apps that are NOT yet in the
``.importlinter`` baseline (only ``patient_portal -> emr`` is):

  * ``apps.whatsapp.slot_service`` (slot engine — S5-T1)
  * ``apps.billing`` models + ``AsaasService`` (receivables + PIX — S5-T2)

They follow the exact same direct-import pattern the existing portal uses for
``apps.emr``; the parent must grandfather ``patient_portal -> whatsapp`` and
``patient_portal -> billing`` into ``ignore_imports`` (or route them through a
core seam).
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from apps.billing.models import AccountsReceivable, PIXCharge
from apps.billing.services.asaas import AsaasAPIError, AsaasService
from apps.core.models import AuditLog
from apps.emr.models import (
    Appointment,
    ClinicalFormResponse,
    ClinicalFormTemplate,
    Encounter,
    Professional,
    ScheduleConfig,
)
from apps.emr.services.scheduling import AppointmentSchedulingService
from apps.whatsapp.slot_service import get_available_slots

from .models import PortalConsent
from .transactional_models import (
    PortalPixPayment,
    PortalPreConsultForm,
    PortalScheduleRequest,
)
from .views import _SelfView

# LGPD consent purposes for the transactional portal (reuse PortalConsent).
CONSENT_SCHEDULING = "portal_scheduling"
CONSENT_PAYMENT = "portal_payment"
CONSENT_PRECONSULT = "portal_pre_consult"

# Receivable statuses a patient may still settle from the portal.
_OPEN_RECEIVABLE_STATUSES = ["expected", "billed", "overdue"]


def _has_valid_consent(patient, purpose: str) -> bool:
    """True if the patient has a currently-valid PortalConsent for ``purpose``."""
    return any(c.is_valid() for c in patient.portal_consents.filter(purpose=purpose))


def _consent_for(patient, purpose: str) -> PortalConsent | None:
    return next(
        (c for c in patient.portal_consents.filter(purpose=purpose) if c.is_valid()),
        None,
    )


def _consent_required_response() -> Response:
    return Response(
        {"detail": "Consentimento LGPD necessário para esta operação."},
        status=status.HTTP_403_FORBIDDEN,
    )


# ─── S5-T1 · Self-service scheduling ───────────────────────────────────────────


class MeAvailableSlotsView(_SelfView):
    """GET `/portal/me/schedule/slots/?professional=<id>&days=<n>`.

    Availability comes straight from the shared ``slot_service`` engine — the
    portal never reimplements slot maths.
    """

    def get(self, request):
        self._patient(request)  # touch + enforce self-access
        professional_id = request.query_params.get("professional")
        if not professional_id:
            return Response(
                {"detail": "Parâmetro 'professional' obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            professional = Professional.objects.get(pk=professional_id)
        except (Professional.DoesNotExist, ValueError):
            return Response(
                {"detail": "Profissional não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            days = int(request.query_params.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        slots = get_available_slots(professional, days_ahead=days)
        payload = {
            day: [{"start": s.start_iso, "end": s.end_iso, "label": s.label} for s in day_slots]
            for day, day_slots in slots.items()
        }
        return Response({"professional": str(professional.pk), "slots": payload})


class MeBookAppointmentView(_SelfView):
    """POST `/portal/me/appointments/book/` — book a self-service appointment."""

    def post(self, request):
        patient = self._patient(request)
        if not _has_valid_consent(patient, CONSENT_SCHEDULING):
            return _consent_required_response()

        professional_id = request.data.get("professional")
        start_raw = request.data.get("start_time")
        if not professional_id or not start_raw:
            return Response(
                {"detail": "'professional' e 'start_time' são obrigatórios."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            professional = Professional.objects.get(pk=professional_id)
        except (Professional.DoesNotExist, ValueError):
            return Response(
                {"detail": "Profissional não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

        start_time = _parse_dt(start_raw)
        if start_time is None:
            return Response(
                {"detail": "start_time inválido (use ISO 8601)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        end_time = _resolve_end_time(request.data.get("end_time"), start_time, professional)

        service = AppointmentSchedulingService(requesting_user=request.user)
        try:
            appointment = service.create(
                patient=patient,
                professional=professional,
                start_time=start_time,
                end_time=end_time,
                type="consultation",
                status="scheduled",
                source="web",
            )
        except (ValidationError, PermissionDenied) as exc:
            return Response(
                {"detail": "Horário indisponível.", "error": _err_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        self._record(request, patient, appointment, PortalScheduleRequest.ACTION_BOOK)
        return Response(_appt_dict(appointment), status=status.HTTP_201_CREATED)

    def _record(self, request, patient, appointment, action):
        _record_schedule_request(request, patient, appointment, action)


class MeRescheduleAppointmentView(_SelfView):
    """POST `/portal/me/appointments/<id>/reschedule/`."""

    def post(self, request, appointment_id):
        patient = self._patient(request)
        if not _has_valid_consent(patient, CONSENT_SCHEDULING):
            return _consent_required_response()

        appointment = _own_appointment(patient, appointment_id)
        if appointment is None:
            return Response(
                {"detail": "Agendamento não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

        start_time = _parse_dt(request.data.get("start_time"))
        if start_time is None:
            return Response(
                {"detail": "start_time inválido (use ISO 8601)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        end_time = _resolve_end_time(
            request.data.get("end_time"), start_time, appointment.professional
        )

        # Reuse the emr availability authority; the new interval must be bookable.
        from apps.emr.services.scheduling import is_professional_available

        if not is_professional_available(appointment.professional, start_time, end_time):
            return Response({"detail": "Horário indisponível."}, status=status.HTTP_400_BAD_REQUEST)

        old = {"start_time": appointment.start_time.isoformat()}
        try:
            with transaction.atomic():
                appointment.start_time = start_time
                appointment.end_time = end_time
                appointment.save()
        except ValidationError as exc:
            return Response(
                {"detail": "Horário indisponível.", "error": _err_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _record_schedule_request(
            request,
            patient,
            appointment,
            PortalScheduleRequest.ACTION_RESCHEDULE,
            detail={"old": old, "new": {"start_time": start_time.isoformat()}},
        )
        return Response(_appt_dict(appointment))


class MeCancelAppointmentView(_SelfView):
    """POST `/portal/me/appointments/<id>/cancel/`."""

    def post(self, request, appointment_id):
        patient = self._patient(request)
        if not _has_valid_consent(patient, CONSENT_SCHEDULING):
            return _consent_required_response()

        appointment = _own_appointment(patient, appointment_id)
        if appointment is None:
            return Response(
                {"detail": "Agendamento não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

        reason = request.data.get("reason", "")
        appointment.status = "cancelled"
        appointment.cancelled_by = request.user
        appointment.cancellation_reason = reason
        appointment.save(update_fields=["status", "cancelled_by", "cancellation_reason"])

        _record_schedule_request(
            request,
            patient,
            appointment,
            PortalScheduleRequest.ACTION_CANCEL,
            detail={"reason": reason},
        )
        return Response(_appt_dict(appointment))


# ─── S5-T2 · PIX payment ───────────────────────────────────────────────────────


class MeReceivablesView(_SelfView):
    """GET `/portal/me/receivables/` — the patient's own open receivables.

    Uses the origin-agnostic ``AccountsReceivable.patient`` FK (M1 integration),
    so guia-less private/PIX/package receivables are visible too.
    """

    def get(self, request):
        patient = self._patient(request)
        qs = AccountsReceivable.objects.filter(
            patient=patient, status__in=_OPEN_RECEIVABLE_STATUSES
        ).select_related("guide")
        data = [_receivable_dict(r) for r in qs[:200]]
        return Response(data)


class MeReceivablePixView(_SelfView):
    """POST `/portal/me/receivables/<id>/pix/` — raise a PIX charge for one."""

    def post(self, request, receivable_id):
        patient = self._patient(request)
        if not _has_valid_consent(patient, CONSENT_PAYMENT):
            return _consent_required_response()

        try:
            receivable = AccountsReceivable.objects.select_related(
                "guide", "guide__encounter", "guide__encounter__appointment"
            ).get(pk=receivable_id, patient=patient)
        except (AccountsReceivable.DoesNotExist, ValueError):
            # 404 (not 403) so a patient can't probe other patients' receivable ids.
            return Response(
                {"detail": "Recebível não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )

        # PIXCharge is appointment-bound (OneToOne). Derive the appointment from
        # the receivable's guide → encounter → appointment chain.
        # COUPLING ASSUMPTION (for parent/S4): the receivable must resolve to an
        # appointment; when S4 untethers AR this derivation should be revisited.
        appointment = _appointment_for_receivable(receivable)
        if appointment is None:
            return Response(
                {"detail": "Recebível sem agendamento associado para cobrança PIX."},
                status=status.HTTP_409_CONFLICT,
            )

        # Idempotent: reuse an existing pending charge for this appointment.
        existing = PIXCharge.objects.filter(
            appointment=appointment, status=PIXCharge.Status.PENDING
        ).first()
        if existing:
            return Response(_pix_dict(existing), status=status.HTTP_200_OK)

        try:
            service = AsaasService()
            charge_data = service.create_pix_charge(appointment, receivable.amount)
        except AsaasAPIError as exc:
            return Response(exc.to_response_dict(), status=status.HTTP_503_SERVICE_UNAVAILABLE)

        with transaction.atomic():
            charge = PIXCharge.objects.create(
                appointment=appointment,
                asaas_charge_id=charge_data["asaas_charge_id"],
                asaas_customer_id=charge_data.get("asaas_customer_id", ""),
                amount=receivable.amount,
                pix_copy_paste=charge_data.get("pix_copy_paste", ""),
                pix_qr_code_base64=charge_data.get("pix_qr_code_base64", ""),
                expires_at=charge_data["expires_at"],
            )
            PortalPixPayment.objects.create(
                patient=patient,
                receivable_ref=str(receivable.pk),
                pix_charge=charge,
                amount=receivable.amount,
                consent=_consent_for(patient, CONSENT_PAYMENT),
                initiated_by=request.user,
            )
            AuditLog.objects.create(
                user=request.user,
                action="portal_pix_charge_initiated",
                resource_type="pixcharge",
                resource_id=str(charge.pk),
                new_data={
                    "receivable_id": str(receivable.pk),
                    "amount": str(receivable.amount),
                },
            )
        return Response(_pix_dict(charge), status=status.HTTP_201_CREATED)


# ─── S5-T3 · Pre-consult forms ─────────────────────────────────────────────────


class MePreConsultFormView(_SelfView):
    """GET/POST `/portal/me/appointments/<id>/pre-consult-form/`.

    GET returns the assigned template schema; POST submits the (encrypted)
    answers as an ``emr.ClinicalFormResponse`` linked to the appointment's
    encounter.
    """

    def get(self, request, appointment_id):
        patient = self._patient(request)
        appointment = _own_appointment(patient, appointment_id)
        if appointment is None:
            return Response(
                {"detail": "Agendamento não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
        assignment = appointment.portal_pre_consult_forms.select_related("template").first()
        if assignment is None:
            return Response(
                {"detail": "Nenhum formulário pré-consulta atribuído."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(_assignment_dict(assignment))

    def post(self, request, appointment_id):
        patient = self._patient(request)
        if not _has_valid_consent(patient, CONSENT_PRECONSULT):
            return _consent_required_response()

        appointment = _own_appointment(patient, appointment_id)
        if appointment is None:
            return Response(
                {"detail": "Agendamento não encontrado."}, status=status.HTTP_404_NOT_FOUND
            )
        assignment = (
            appointment.portal_pre_consult_forms.select_related("template")
            .filter(status=PortalPreConsultForm.STATUS_ASSIGNED)
            .first()
        )
        if assignment is None:
            return Response(
                {"detail": "Nenhum formulário pré-consulta pendente."},
                status=status.HTTP_404_NOT_FOUND,
            )

        answers = request.data.get("answers")
        template: ClinicalFormTemplate = assignment.template

        try:
            with transaction.atomic():
                encounter = _encounter_for_appointment(appointment)
                response = ClinicalFormResponse(
                    template=template,
                    encounter=encounter,
                    patient=patient,
                    answers=answers if answers is not None else {},
                    filled_by=request.user,
                )
                response.save()  # full_clean() validates answers against schema
                assignment.response = response
                assignment.status = PortalPreConsultForm.STATUS_SUBMITTED
                assignment.save(update_fields=["response", "status", "updated_at"])
                AuditLog.objects.create(
                    user=request.user,
                    action="portal_pre_consult_submitted",
                    resource_type="clinicalformresponse",
                    resource_id=str(response.pk),
                    new_data={
                        "appointment_id": str(appointment.pk),
                        "template_id": str(template.pk),
                    },
                )
        except ValidationError as exc:
            return Response(
                {"detail": "Respostas inválidas.", "error": _err_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"id": str(response.pk), "status": assignment.status},
            status=status.HTTP_201_CREATED,
        )


# ─── helpers ───────────────────────────────────────────────────────────────────


def _record_schedule_request(request, patient, appointment, action, detail=None):
    consent = _consent_for(patient, CONSENT_SCHEDULING)
    PortalScheduleRequest.objects.create(
        patient=patient,
        appointment=appointment,
        action=action,
        consent=consent,
        requested_by=request.user,
        detail=detail or {},
    )
    AuditLog.objects.create(
        user=request.user,
        action=f"portal_appointment_{action}",
        resource_type="appointment",
        resource_id=str(appointment.pk),
        new_data=detail or {},
    )


def _own_appointment(patient, appointment_id):
    try:
        return Appointment.objects.get(pk=appointment_id, patient=patient)
    except (Appointment.DoesNotExist, ValueError):
        return None


def _appointment_for_receivable(receivable):
    guide = getattr(receivable, "guide", None)
    encounter = getattr(guide, "encounter", None) if guide is not None else None
    return getattr(encounter, "appointment", None) if encounter is not None else None


def _encounter_for_appointment(appointment) -> Encounter:
    """Return the appointment's encounter, creating an open one if absent."""
    encounter = getattr(appointment, "encounter", None)
    if encounter is not None:
        return encounter
    return Encounter.objects.create(
        patient=appointment.patient,
        professional=appointment.professional,
        appointment=appointment,
        status="open",
    )


def _resolve_end_time(raw_end, start_time, professional):
    end = _parse_dt(raw_end) if raw_end else None
    if end is not None:
        return end
    minutes = 30
    config = ScheduleConfig.objects.filter(professional=professional).first()
    if config is not None:
        minutes = config.slot_duration_minutes
    return start_time + timedelta(minutes=minutes)


def _parse_dt(raw):
    if not raw:
        return None
    from django.utils.dateparse import parse_datetime

    if not isinstance(raw, str):
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _err_detail(exc):
    if isinstance(exc, ValidationError):
        return getattr(exc, "message_dict", None) or getattr(exc, "messages", str(exc))
    return str(exc)


def _appt_dict(appointment) -> dict:
    return {
        "id": str(appointment.pk),
        "patient": str(appointment.patient_id),
        "professional": str(appointment.professional_id),
        "start_time": appointment.start_time.isoformat(),
        "end_time": appointment.end_time.isoformat(),
        "status": appointment.status,
        "source": appointment.source,
    }


def _receivable_dict(receivable) -> dict:
    return {
        "id": str(receivable.pk),
        "amount": str(receivable.amount),
        "status": receivable.status,
        "due_date": receivable.due_date.isoformat() if receivable.due_date else None,
    }


def _pix_dict(charge) -> dict:
    return {
        "id": str(charge.pk),
        "appointment_id": str(charge.appointment_id),
        "amount": str(charge.amount),
        "status": charge.status,
        "pix_copy_paste": charge.pix_copy_paste,
        "pix_qr_code_base64": charge.pix_qr_code_base64,
        "expires_at": charge.expires_at.isoformat() if charge.expires_at else None,
    }


def _assignment_dict(assignment) -> dict:
    template = assignment.template
    return {
        "id": str(assignment.pk),
        "appointment_id": str(assignment.appointment_id),
        "status": assignment.status,
        "template": {
            "id": str(template.pk),
            "name": template.name,
            "specialty": template.specialty,
            "version": template.version,
            "schema": template.schema,
        },
    }
