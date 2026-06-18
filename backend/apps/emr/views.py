from datetime import datetime, timedelta

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.mixins import AuditReadMixin
from apps.core.models import AuditLog
from apps.core.permissions import HasPermission

from .filters import PatientFilter, PatientSearchFilter
from .models import (
    Appointment,
    ClinicalDocument,
    Encounter,
    EncounterProcedure,
    Patient,
    PatientInsurance,
    Prescription,
    PrescriptionItem,
    Professional,
    ScheduleConfig,
    SOAPNote,
    VitalSigns,
)
from .serializers import (
    AllergySerializer,
    AppointmentSerializer,
    ClinicalDocumentSerializer,
    EncounterListSerializer,
    EncounterProcedureSerializer,
    EncounterSerializer,
    MedicalHistorySerializer,
    PatientCreateSerializer,
    PatientInsuranceSerializer,
    PatientListSerializer,
    PatientSerializer,
    PrescriptionItemSerializer,
    PrescriptionSerializer,
    ProfessionalSerializer,
    ScheduleConfigSerializer,
    SOAPNoteSerializer,
    VitalSignsSerializer,
)


def log_audit(request, action, resource_type, resource_id, old_data=None, new_data=None):
    AuditLog.objects.create(
        user=request.user,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        old_data=old_data,
        new_data=new_data,
        ip_address=request.META.get("REMOTE_ADDR", ""),
    )


class PatientViewSet(AuditReadMixin, viewsets.ModelViewSet):
    audit_resource_type = "Patient"
    permission_classes = [IsAuthenticated, HasPermission("emr.read")]  # type: ignore[list-item]
    # full_name / social_name are encrypted at rest (LGPD): they cannot be
    # searched or ordered in SQL. Name search is handled in Python by
    # PatientSearchFilter; full_name is dropped from ordering_fields and the
    # default order falls back to the (sequential) medical record number.
    filter_backends = [DjangoFilterBackend, PatientSearchFilter, filters.OrderingFilter]
    filterset_class = PatientFilter
    ordering_fields = ["birth_date", "created_at", "medical_record_number"]
    ordering = ["medical_record_number"]

    def get_queryset(self):
        return (
            Patient.objects.select_related("created_by")
            .prefetch_related("allergies", "medical_history")
            .filter(is_active=True)
        )

    def get_serializer_class(self):
        if self.action == "list":
            return PatientListSerializer
        if self.action == "create":
            return PatientCreateSerializer
        return PatientSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update"):
            return [IsAuthenticated(), HasPermission("emr.write")]
        if self.action == "destroy":
            return [IsAuthenticated(), HasPermission("admin")]
        return super().get_permissions()

    def perform_create(self, serializer):
        patient = serializer.save(created_by=self.request.user)
        from apps.emr.services.patient_registration import PatientRegistrationService

        service = PatientRegistrationService(requesting_user=self.request.user)
        service.register(patient)

    def perform_update(self, serializer):
        old = PatientSerializer(self.get_object()).data
        patient = serializer.save()
        log_audit(
            self.request,
            "patient_update",
            "Patient",
            patient.id,
            old_data=old,
            new_data=PatientSerializer(patient).data,
        )

    def perform_destroy(self, instance):
        old_data = {"is_active": True}
        instance.is_active = False
        instance.save()
        log_audit(self.request, "patient_deactivate", "Patient", instance.id, old_data=old_data)

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        patient = self.get_object()
        encounters = (
            Encounter.objects.filter(patient=patient)
            .select_related("professional__user")
            .order_by("-encounter_date")[:20]
        )
        events = [
            {
                "type": "encounter",
                "id": str(e.id),
                "date": e.encounter_date.isoformat(),
                "status": e.status,
                "professional": e.professional.user.full_name,
                "chief_complaint": e.chief_complaint,
            }
            for e in encounters
        ]
        return Response({"patient_id": str(patient.id), "events": events})

    @action(detail=True, methods=["get", "post"])
    def allergies(self, request, pk=None):
        patient = self.get_object()
        if request.method == "GET":
            serializer = AllergySerializer(patient.allergies.all(), many=True)
            return Response(serializer.data)
        serializer = AllergySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allergy = serializer.save(patient=patient)
        log_audit(
            request,
            "allergy_create",
            "Allergy",
            allergy.id,
            new_data={"substance": allergy.substance, "severity": allergy.severity},
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="medical-history")
    def medical_history(self, request, pk=None):
        patient = self.get_object()
        if request.method == "GET":
            serializer = MedicalHistorySerializer(patient.medical_history.all(), many=True)
            return Response(serializer.data)
        serializer = MedicalHistorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = serializer.save(patient=patient)
        log_audit(request, "medical_history_create", "MedicalHistory", record.id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="insurance")
    def insurance(self, request, pk=None):
        """
        GET  /api/v1/emr/patients/{id}/insurance/  — list all insurance cards for patient
        POST /api/v1/emr/patients/{id}/insurance/  — add a new insurance card
        """
        patient = self.get_object()
        if request.method == "GET":
            serializer = PatientInsuranceSerializer(patient.insurance_cards.all(), many=True)
            return Response(serializer.data)
        serializer = PatientInsuranceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        card = serializer.save(patient=patient)
        log_audit(
            request,
            "insurance_create",
            "PatientInsurance",
            card.id,
            new_data={
                "provider_ans_code": card.provider_ans_code,
                "provider_name": card.provider_name,
            },
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"insurance/(?P<card_pk>[^/.]+)",
    )
    def insurance_detail(self, request, pk=None, card_pk=None):
        """
        PATCH  /api/v1/emr/patients/{id}/insurance/{card_id}/  — update a card
        DELETE /api/v1/emr/patients/{id}/insurance/{card_id}/  — remove a card
        """
        patient = self.get_object()
        try:
            card = patient.insurance_cards.get(pk=card_pk)
        except PatientInsurance.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if request.method == "DELETE":
            card.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = PatientInsuranceSerializer(card, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ProfessionalViewSet(viewsets.ModelViewSet):
    queryset = Professional.objects.select_related("user").filter(is_active=True)
    serializer_class = ProfessionalSerializer
    permission_classes = [IsAuthenticated, HasPermission("admin")]  # type: ignore[list-item]
    filter_backends = [filters.SearchFilter]
    search_fields = ["user__full_name", "council_number", "specialty"]


class ScheduleConfigViewSet(viewsets.ModelViewSet):
    queryset = ScheduleConfig.objects.select_related("professional__user").all()
    serializer_class = ScheduleConfigSerializer
    permission_classes = [IsAuthenticated, HasPermission("admin")]  # type: ignore[list-item]


class AppointmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasPermission("schedule.read")]  # type: ignore[list-item]
    serializer_class = AppointmentSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering = ["start_time"]

    def get_queryset(self):
        qs = Appointment.objects.select_related(
            "patient", "professional__user", "created_by"
        ).filter(start_time__date__gte=timezone.localdate())

        date_param = self.request.query_params.get("date")
        if date_param:
            try:
                d = datetime.strptime(date_param, "%Y-%m-%d").date()
                qs = qs.filter(start_time__date=d)
            except ValueError:
                pass

        professional_id = self.request.query_params.get("professional_id")
        if professional_id:
            qs = qs.filter(professional_id=professional_id)

        patient_id = self.request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)

        return qs

    def get_permissions(self):
        if self.action in (
            "create",
            "update",
            "partial_update",
            "update_status",
            "check_in",
            "start",
        ):
            return [IsAuthenticated(), HasPermission("schedule.write")]
        return super().get_permissions()

    def perform_create(self, serializer):
        try:
            appointment = serializer.save(created_by=self.request.user)
        except Exception as exc:
            msg = str(exc)
            if "TIME_SLOT_UNAVAILABLE" in msg:
                from rest_framework.exceptions import ValidationError as DRFValidationError

                raise DRFValidationError({"start_time": "TIME_SLOT_UNAVAILABLE"}) from exc
            raise
        from apps.emr.services.appointment_creation import AppointmentCreationService

        AppointmentCreationService(requesting_user=self.request.user).create(appointment)

    @action(detail=False, methods=["get"])
    def today(self, request):
        today = timezone.localdate()
        qs = (
            Appointment.objects.select_related("patient", "professional__user")
            .filter(start_time__date=today)
            .order_by("start_time")
        )
        return Response(AppointmentSerializer(qs, many=True).data)

    @action(detail=True, methods=["patch"], url_path="status")
    def update_status(self, request, pk=None):
        appointment = self.get_object()
        new_status = request.data.get("status")
        valid = [s[0] for s in Appointment.STATUS_CHOICES]
        if new_status not in valid:
            return Response(
                {"error": {"code": "INVALID_STATUS", "message": f"Status deve ser um de: {valid}"}},
                status=400,
            )
        old_status = appointment.status
        appointment.status = new_status
        appointment.save(update_fields=["status", "updated_at"])
        log_audit(
            request,
            "appointment_status_change",
            "Appointment",
            appointment.id,
            old_data={"status": old_status},
            new_data={"status": new_status},
        )
        return Response(AppointmentSerializer(appointment).data)

    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, pk=None):
        """POST /appointments/{id}/check-in/ — registra chegada do paciente (idempotente)."""
        appointment = self.get_object()
        if appointment.arrived_at is not None:
            # Already checked in — idempotent, return current state unchanged
            return Response(AppointmentSerializer(appointment).data)
        appointment.arrived_at = timezone.now()
        appointment.status = "waiting"
        appointment.save(update_fields=["arrived_at", "status", "updated_at"])
        log_audit(
            request,
            "appointment_check_in",
            "Appointment",
            appointment.id,
            new_data={"arrived_at": appointment.arrived_at.isoformat(), "status": "waiting"},
        )
        return Response(AppointmentSerializer(appointment).data)

    @action(detail=True, methods=["post"], url_path="start")
    def start(self, request, pk=None):
        """POST /appointments/{id}/start/ — inicia atendimento e abre a consulta vinculada."""
        appointment = self.get_object()
        if appointment.status in {"completed", "cancelled", "no_show"}:
            return Response(
                {
                    "error": {
                        "code": "APPOINTMENT_NOT_STARTABLE",
                        "message": "Agendamento concluído, cancelado ou faltante não pode ser iniciado.",
                    }
                },
                status=400,
            )

        old_status = appointment.status
        if appointment.started_at is None:
            appointment.started_at = timezone.now()
        appointment.status = "in_progress"
        appointment.save(update_fields=["started_at", "status", "updated_at"])

        encounter, created = Encounter.objects.get_or_create(
            appointment=appointment,
            defaults={
                "patient": appointment.patient,
                "professional": appointment.professional,
                "encounter_date": appointment.started_at,
                "chief_complaint": appointment.notes,
            },
        )
        SOAPNote.objects.get_or_create(encounter=encounter)
        # VitalSigns is a time-series (FK): ensure one editable row exists at
        # check-in without get_or_create, which would raise once a second
        # reading is added for the encounter.
        if not VitalSigns.objects.filter(encounter=encounter).exists():
            VitalSigns.objects.create(encounter=encounter)

        log_audit(
            request,
            "appointment_start",
            "Appointment",
            appointment.id,
            old_data={"status": old_status},
            new_data={
                "started_at": appointment.started_at.isoformat(),
                "status": "in_progress",
                "encounter_id": str(encounter.id),
                "encounter_created": created,
            },
        )
        data = AppointmentSerializer(appointment).data
        data["encounter_id"] = str(encounter.id)
        data["encounter_created"] = created
        return Response(data)


class AvailableSlotsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, professional_id):
        date_str = request.query_params.get("date")
        duration = int(request.query_params.get("duration", 30))

        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return Response(
                {"error": {"code": "INVALID_DATE", "message": "Formato: YYYY-MM-DD"}},
                status=400,
            )

        try:
            professional = Professional.objects.get(id=professional_id, is_active=True)
            config = professional.schedule_config
        except Professional.DoesNotExist:
            return Response(
                {"error": {"code": "NOT_FOUND", "message": "Profissional não encontrado"}},
                status=404,
            )
        except ScheduleConfig.DoesNotExist:
            return Response({"slots": [], "message": "Profissional sem agenda configurada"})

        weekday = target_date.weekday()
        working_days = config.working_days if config.working_days else [0, 1, 2, 3, 4]
        if weekday not in working_days:
            return Response({"slots": [], "message": "Profissional não atende neste dia"})

        slots = []
        current = datetime.combine(target_date, config.working_hours_start)
        end = datetime.combine(target_date, config.working_hours_end)
        slot_delta = timedelta(minutes=duration)

        booked = list(
            Appointment.objects.filter(
                professional=professional,
                start_time__date=target_date,
                status__in=["scheduled", "confirmed", "waiting", "in_progress"],
            ).values_list("start_time", "end_time")
        )
        booked_naive = [
            (s.replace(tzinfo=None) if s.tzinfo else s, e.replace(tzinfo=None) if e.tzinfo else e)
            for s, e in booked
        ]
        now_naive = timezone.now().replace(tzinfo=None)

        while current + slot_delta <= end:
            slot_end = current + slot_delta
            if config.lunch_start and config.lunch_end:
                lunch_s = datetime.combine(target_date, config.lunch_start)
                lunch_e = datetime.combine(target_date, config.lunch_end)
                if current < lunch_e and slot_end > lunch_s:
                    current = lunch_e
                    continue
            is_available = not any(current < e and slot_end > s for s, e in booked_naive)
            slots.append(
                {
                    "start": current.isoformat(),
                    "end": slot_end.isoformat(),
                    "available": is_available and current > now_naive,
                }
            )
            current += slot_delta

        return Response({"date": date_str, "professional_id": str(professional_id), "slots": slots})


class WaitingRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        waiting = (
            Appointment.objects.select_related("patient", "professional__user")
            .filter(
                start_time__date=today,
                status__in=["scheduled", "confirmed", "waiting"],
            )
            .order_by("start_time")
        )
        return Response(AppointmentSerializer(waiting, many=True).data)


# ─── Sprint 4: EMR Core views ─────────────────────────────────────────────────


class EncounterViewSet(AuditReadMixin, viewsets.ModelViewSet):
    """Consultas clínicas — ponto central do EMR"""

    audit_resource_type = "Encounter"
    permission_classes = [IsAuthenticated, HasPermission("emr.read")]  # type: ignore[list-item]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering = ["-encounter_date"]

    def get_queryset(self):
        qs = Encounter.objects.select_related(
            "patient",
            "professional__user",
            "appointment",
        ).prefetch_related("soap_note", "vital_signs", "documents", "patient__allergies")

        patient_id = self.request.query_params.get("patient_id")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)

        professional_id = self.request.query_params.get("professional_id")
        if professional_id:
            qs = qs.filter(professional_id=professional_id)

        enc_status = self.request.query_params.get("status")
        if enc_status:
            qs = qs.filter(status=enc_status)

        date_param = self.request.query_params.get("date")
        if date_param:
            try:
                d = datetime.strptime(date_param, "%Y-%m-%d").date()
                qs = qs.filter(encounter_date__date=d)
            except ValueError:
                pass

        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return EncounterListSerializer
        return EncounterSerializer

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "sign"):
            return [IsAuthenticated(), HasPermission("emr.write")]
        if self.action == "destroy":
            return [IsAuthenticated(), HasPermission("admin")]
        # Nested procedures: writes require emr.write, reads emr.read. Clinical
        # capture is NOT gated behind the billing module by design.
        if self.action in ("procedures", "procedure_detail"):
            if self.request.method in ("POST", "PATCH", "PUT", "DELETE"):
                return [IsAuthenticated(), HasPermission("emr.write")]
            return [IsAuthenticated(), HasPermission("emr.read")]
        return super().get_permissions()

    def perform_create(self, serializer):
        encounter = serializer.save()
        # Auto-create empty SOAP note and vital signs
        SOAPNote.objects.get_or_create(encounter=encounter)
        # VitalSigns is a time-series (FK): ensure one editable row exists at
        # check-in without get_or_create, which would raise once a second
        # reading is added for the encounter.
        if not VitalSigns.objects.filter(encounter=encounter).exists():
            VitalSigns.objects.create(encounter=encounter)
        log_audit(
            self.request,
            "encounter_create",
            "Encounter",
            encounter.id,
            new_data={
                "patient": str(encounter.patient_id),
                "professional": str(encounter.professional_id),
                "encounter_date": str(encounter.encounter_date),
            },
        )

    def perform_update(self, serializer):
        encounter = serializer.save()
        log_audit(self.request, "encounter_update", "Encounter", encounter.id)

    @action(detail=True, methods=["post"])
    def sign(self, request, pk=None):
        """POST /encounters/{id}/sign/ — assina a consulta + cascade F-03."""
        encounter = self.get_object()
        if encounter.status != "open":
            return Response(
                {
                    "error": {
                        "code": "ENCOUNTER_NOT_OPEN",
                        "message": "Apenas consultas abertas podem ser assinadas.",
                    }
                },
                status=400,
            )
        from apps.emr.services.encounter_signing import EncounterSigningService

        service = EncounterSigningService(requesting_user=request.user)
        service.sign(
            encounter,
            pkcs12_b64=request.data.get("pkcs12_b64"),
            pkcs12_password=request.data.get("pkcs12_password"),
        )
        return Response(EncounterSerializer(encounter).data)

    @staticmethod
    def _encounter_not_open_response():
        return Response(
            {
                "error": {
                    "code": "ENCOUNTER_NOT_OPEN",
                    "message": "Procedimentos só podem ser alterados em consultas abertas.",
                }
            },
            status=status.HTTP_409_CONFLICT,
        )

    @action(detail=True, methods=["get", "post"], url_path="procedures")
    def procedures(self, request, pk=None):
        """
        GET  /api/v1/encounters/{id}/procedures/  — list procedures (any status)
        POST /api/v1/encounters/{id}/procedures/  — add a procedure (open only)
        """
        encounter = self.get_object()
        if request.method == "GET":
            qs = encounter.procedures.select_related("tuss_code", "performed_by__user")
            return Response(EncounterProcedureSerializer(qs, many=True).data)
        # POST — capture is allowed only while the encounter is open.
        if encounter.status != "open":
            return self._encounter_not_open_response()
        serializer = EncounterProcedureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        procedure = serializer.save(encounter=encounter)
        log_audit(
            request,
            "encounter_procedure_create",
            "EncounterProcedure",
            procedure.id,
            new_data={
                "encounter": str(encounter.id),
                "tuss_code": str(procedure.tuss_code_id),
                "quantity": str(procedure.quantity),
            },
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"procedures/(?P<proc_pk>[0-9a-f-]+)",
    )
    def procedure_detail(self, request, pk=None, proc_pk=None):
        """
        PATCH  /api/v1/encounters/{id}/procedures/{proc_id}/  — update (open only)
        DELETE /api/v1/encounters/{id}/procedures/{proc_id}/  — remove (open only)
        """
        encounter = self.get_object()
        try:
            procedure = encounter.procedures.select_related("tuss_code").get(pk=proc_pk)
        except EncounterProcedure.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if encounter.status != "open":
            return self._encounter_not_open_response()
        if request.method == "DELETE":
            proc_id = procedure.id
            procedure.delete()
            log_audit(
                request,
                "encounter_procedure_delete",
                "EncounterProcedure",
                proc_id,
                old_data={"encounter": str(encounter.id)},
            )
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = EncounterProcedureSerializer(procedure, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        log_audit(
            request,
            "encounter_procedure_update",
            "EncounterProcedure",
            procedure.id,
            new_data={"quantity": str(procedure.quantity)},
        )
        return Response(serializer.data)


class SOAPNoteViewSet(viewsets.ModelViewSet):
    """Notas SOAP — somente PATCH, nunca DELETE"""

    queryset = SOAPNote.objects.select_related("encounter").all()
    serializer_class = SOAPNoteSerializer
    permission_classes = [IsAuthenticated, HasPermission("emr.write")]  # type: ignore[list-item]
    http_method_names = ["get", "patch", "head", "options"]

    def perform_update(self, serializer):
        soap = serializer.save()
        log_audit(
            self.request,
            "soap_note_update",
            "SOAPNote",
            soap.id,
            new_data={
                "encounter": str(soap.encounter_id),
                "updated_at": str(soap.updated_at),
            },
        )


class VitalSignsViewSet(viewsets.ModelViewSet):
    """Sinais vitais"""

    queryset = VitalSigns.objects.select_related("encounter").all()
    serializer_class = VitalSignsSerializer
    permission_classes = [IsAuthenticated, HasPermission("emr.write")]  # type: ignore[list-item]
    http_method_names = ["get", "patch", "head", "options"]

    def perform_update(self, serializer):
        vs = serializer.save()
        log_audit(
            self.request,
            "vital_signs_update",
            "VitalSigns",
            vs.id,
            new_data={"encounter": str(vs.encounter_id)},
        )


class ClinicalDocumentViewSet(viewsets.ModelViewSet):
    """Documentos clínicos — atestado, receita, encaminhamento"""

    queryset = ClinicalDocument.objects.select_related("encounter", "signed_by").all()
    serializer_class = ClinicalDocumentSerializer
    permission_classes = [IsAuthenticated, HasPermission("emr.write")]  # type: ignore[list-item]
    filter_backends = [DjangoFilterBackend]

    def get_queryset(self):
        qs = super().get_queryset()
        encounter_id = self.request.query_params.get("encounter_id")
        if encounter_id:
            qs = qs.filter(encounter_id=encounter_id)
        return qs

    def perform_create(self, serializer):
        doc = serializer.save()
        log_audit(
            self.request,
            "document_create",
            "ClinicalDocument",
            doc.id,
            new_data={"doc_type": doc.doc_type, "encounter": str(doc.encounter_id)},
        )

    @action(detail=True, methods=["post"])
    def sign(self, request, pk=None):
        """POST /documents/{id}/sign/ — assina o documento"""
        doc = self.get_object()
        if doc.is_signed:
            return Response(
                {"error": "Documento já assinado."}, status=status.HTTP_409_CONFLICT
            )

        from apps.emr.services.icp_brasil_integration import sign_with_icp_brasil

        is_icp, sig_hash = sign_with_icp_brasil(
            user=request.user,
            document_type="custom",
            document_id=str(doc.id),
            document_content=doc.content.encode("utf-8") if doc.content else b"",
            pkcs12_b64=request.data.get("pkcs12_b64"),
            pkcs12_password=request.data.get("pkcs12_password"),
        )
        doc.sign(request.user, is_icp_brasil=is_icp, signature_hash=sig_hash)

        log_audit(
            request,
            "document_sign",
            "ClinicalDocument",
            doc.id,
            new_data={"signed_by": str(request.user.id), "signed_at": str(doc.signed_at)},
        )
        return Response(ClinicalDocumentSerializer(doc).data)


# ─── Sprint 7 (S-015): Prescription ───────────────────────────────────────────


class PrescriptionViewSet(viewsets.ModelViewSet):
    """Receitas médicas — criação, listagem, assinatura."""

    serializer_class = PrescriptionSerializer

    def get_queryset(self):
        qs = Prescription.objects.select_related(
            "encounter", "patient", "prescriber", "signed_by"
        ).prefetch_related("items__drug")
        patient_id = self.request.query_params.get("patient")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        encounter_id = self.request.query_params.get("encounter")
        if encounter_id:
            qs = qs.filter(encounter_id=encounter_id)
        rx_status = self.request.query_params.get("status")
        if rx_status:
            qs = qs.filter(status=rx_status)
        return qs

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy", "sign"):
            return [IsAuthenticated(), HasPermission("emr.write")]
        return [IsAuthenticated(), HasPermission("emr.read")]

    def perform_create(self, serializer):
        rx = serializer.save()
        log_audit(
            self.request,
            "prescription_create",
            "Prescription",
            rx.id,
            new_data={"patient": str(rx.patient_id), "encounter": str(rx.encounter_id)},
        )

    @action(detail=True, methods=["post"])
    def sign(self, request, pk=None):
        """POST /prescriptions/{id}/sign/ — assina a receita (requer emr.sign)."""
        _eff_role = request.user.effective_role()
        if not (request.user.is_superuser or (_eff_role and "emr.sign" in _eff_role.permissions)):
            return Response(
                {"detail": "Permissão emr.sign necessária para assinar receita."},
                status=status.HTTP_403_FORBIDDEN,
            )
        from django.db import transaction

        from apps.emr.services.allergy_safety import AllergySafetyService
        from apps.emr.services.dose_safety import DoseCheckService
        from apps.emr.services.prescription_safety_gate import (
            build_block_payload,
            has_blocking_safety_alert,
        )

        rx = self.get_object()
        if rx.is_signed:
            return Response(
                {"detail": "Receita já assinada."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Prescription-safety soft-stop (dose wedge PR B + allergy wedge PR A1).
        # No-op when both flags are OFF for this tenant — gate behaves exactly as
        # before. Run the deterministic engines BEFORE signing, inside a lock on
        # the prescription, and re-check the generalized blocking predicate under
        # the lock so a concurrent acknowledge/edit can't race the gate.
        with transaction.atomic():
            locked_rx = Prescription.objects.select_for_update().filter(pk=rx.pk).first()
            if locked_rx is None:
                return Response(
                    {"detail": "Receita não encontrada."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            DoseCheckService(requesting_user=request.user).evaluate_prescription(
                locked_rx, gate="sign"
            )
            AllergySafetyService(requesting_user=request.user).evaluate_prescription(
                locked_rx, gate="sign"
            )

            if has_blocking_safety_alert(locked_rx):
                return Response(
                    build_block_payload(locked_rx),
                    status=status.HTTP_409_CONFLICT,
                )

            from apps.emr.services.icp_brasil_integration import sign_with_icp_brasil
            import json

            # Serialize prescription to sign
            doc_content = json.dumps({
                "prescription_id": str(locked_rx.id),
                "patient_id": str(locked_rx.patient_id),
                "notes": locked_rx.notes,
            }, sort_keys=True).encode("utf-8")

            is_icp, sig_hash = sign_with_icp_brasil(
                user=request.user,
                document_type="prescription",
                document_id=str(locked_rx.id),
                document_content=doc_content,
                pkcs12_b64=request.data.get("pkcs12_b64"),
                pkcs12_password=request.data.get("pkcs12_password"),
            )
            locked_rx.sign(request.user, is_icp_brasil=is_icp, signature_hash=sig_hash)

            log_audit(
                request,
                "prescription_sign",
                "Prescription",
                locked_rx.id,
                new_data={
                    "signed_by": str(request.user.id),
                    "signed_at": str(locked_rx.signed_at),
                },
            )
            rx = locked_rx

        return Response(PrescriptionSerializer(rx).data)


class PrescriptionItemViewSet(viewsets.ModelViewSet):
    """Itens de receita — CRUD dentro de uma receita."""

    serializer_class = PrescriptionItemSerializer

    def get_permissions(self):
        return [IsAuthenticated(), HasPermission("emr.write")]

    def get_queryset(self):
        qs = PrescriptionItem.objects.select_related("prescription", "drug")
        prescription_id = self.request.query_params.get("prescription")
        if prescription_id:
            qs = qs.filter(prescription_id=prescription_id)
        return qs

    def perform_create(self, serializer):
        from apps.emr.models import Prescription

        prescription_id = self.request.data.get("prescription")
        try:
            rx = Prescription.objects.get(pk=prescription_id)
        except Prescription.DoesNotExist as exc:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"prescription": "Receita não encontrada."}) from exc
        if rx.status != "draft":
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {
                    "prescription": "Não é possível adicionar itens a uma receita já assinada ou cancelada."
                }
            )
        serializer.save(prescription=rx)

    def perform_update(self, serializer):
        from rest_framework.exceptions import ValidationError

        # Both the CURRENT parent and any TARGET parent (defence in depth — the
        # serializer marks `prescription` read-only, but should that ever change,
        # a PATCH must not move an item onto a signed prescription either) must be
        # draft for the edit to be allowed.
        current_rx = serializer.instance.prescription
        target_rx = serializer.validated_data.get("prescription", current_rx)
        if current_rx.status != "draft" or target_rx.status != "draft":
            raise ValidationError(
                {
                    "prescription": "Não é possível alterar itens de uma receita já assinada ou cancelada."
                }
            )
        serializer.save()

    def perform_destroy(self, instance):
        if instance.prescription.status != "draft":
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {
                    "prescription": "Não é possível alterar itens de uma receita já assinada ou cancelada."
                }
            )
        instance.delete()
