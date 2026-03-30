from datetime import datetime, timedelta

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from apps.core.permissions import HasPermission
from apps.core.models import AuditLog
from .models import (
    Patient, Allergy, MedicalHistory, Professional, Appointment, ScheduleConfig,
    Encounter, SOAPNote, VitalSigns, ClinicalDocument, PatientInsurance,
)
from .serializers import (
    PatientSerializer, PatientListSerializer, PatientCreateSerializer,
    AllergySerializer, MedicalHistorySerializer, ProfessionalSerializer,
    AppointmentSerializer, ScheduleConfigSerializer,
    EncounterSerializer, EncounterListSerializer,
    SOAPNoteSerializer, VitalSignsSerializer, ClinicalDocumentSerializer,
    PatientInsuranceSerializer,
)
from .filters import PatientFilter


def log_audit(request, action, resource_type, resource_id, old_data=None, new_data=None):
    AuditLog.objects.create(
        user=request.user,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        old_data=old_data,
        new_data=new_data,
        ip_address=request.META.get('REMOTE_ADDR', ''),
    )


class PatientViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasPermission('emr.read')]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = PatientFilter
    search_fields = ['full_name', 'social_name', 'medical_record_number', 'whatsapp']
    ordering_fields = ['full_name', 'birth_date', 'created_at', 'medical_record_number']
    ordering = ['full_name']

    def get_queryset(self):
        return Patient.objects.select_related('created_by').prefetch_related(
            'allergies', 'medical_history'
        ).filter(is_active=True)

    def get_serializer_class(self):
        if self.action == 'list':
            return PatientListSerializer
        if self.action == 'create':
            return PatientCreateSerializer
        return PatientSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update'):
            return [IsAuthenticated(), HasPermission('emr.write')]
        if self.action == 'destroy':
            return [IsAuthenticated(), HasPermission('admin')]
        return super().get_permissions()

    def perform_create(self, serializer):
        patient = serializer.save(created_by=self.request.user)
        log_audit(self.request, 'patient_create', 'Patient', patient.id,
                  new_data={'mrn': patient.medical_record_number, 'name': patient.full_name})

    def perform_update(self, serializer):
        old = PatientSerializer(self.get_object()).data
        patient = serializer.save()
        log_audit(self.request, 'patient_update', 'Patient', patient.id,
                  old_data=old, new_data=PatientSerializer(patient).data)

    def perform_destroy(self, instance):
        old_data = {'is_active': True}
        instance.is_active = False
        instance.save()
        log_audit(self.request, 'patient_deactivate', 'Patient', instance.id, old_data=old_data)

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        patient = self.get_object()
        encounters = Encounter.objects.filter(patient=patient).select_related(
            'professional__user'
        ).order_by('-encounter_date')[:20]
        events = [
            {
                'type': 'encounter',
                'id': str(e.id),
                'date': e.encounter_date.isoformat(),
                'status': e.status,
                'professional': e.professional.user.full_name,
                'chief_complaint': e.chief_complaint,
            }
            for e in encounters
        ]
        return Response({'patient_id': str(patient.id), 'events': events})

    @action(detail=True, methods=['get', 'post'])
    def allergies(self, request, pk=None):
        patient = self.get_object()
        if request.method == 'GET':
            serializer = AllergySerializer(patient.allergies.all(), many=True)
            return Response(serializer.data)
        serializer = AllergySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allergy = serializer.save(patient=patient)
        log_audit(request, 'allergy_create', 'Allergy', allergy.id,
                  new_data={'substance': allergy.substance, 'severity': allergy.severity})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='medical-history')
    def medical_history(self, request, pk=None):
        patient = self.get_object()
        if request.method == 'GET':
            serializer = MedicalHistorySerializer(patient.medical_history.all(), many=True)
            return Response(serializer.data)
        serializer = MedicalHistorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = serializer.save(patient=patient)
        log_audit(request, 'medical_history_create', 'MedicalHistory', record.id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get', 'post'], url_path='insurance')
    def insurance(self, request, pk=None):
        """
        GET  /api/v1/emr/patients/{id}/insurance/  — list all insurance cards for patient
        POST /api/v1/emr/patients/{id}/insurance/  — add a new insurance card
        """
        patient = self.get_object()
        if request.method == 'GET':
            serializer = PatientInsuranceSerializer(
                patient.insurance_cards.all(), many=True
            )
            return Response(serializer.data)
        serializer = PatientInsuranceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        card = serializer.save(patient=patient)
        log_audit(request, 'insurance_create', 'PatientInsurance', card.id,
                  new_data={'provider_ans_code': card.provider_ans_code,
                            'provider_name': card.provider_name})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=['patch', 'delete'],
        url_path=r'insurance/(?P<card_pk>[^/.]+)',
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
        if request.method == 'DELETE':
            card.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        serializer = PatientInsuranceSerializer(card, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ProfessionalViewSet(viewsets.ModelViewSet):
    queryset = Professional.objects.select_related('user').filter(is_active=True)
    serializer_class = ProfessionalSerializer
    permission_classes = [IsAuthenticated, HasPermission('admin')]
    filter_backends = [filters.SearchFilter]
    search_fields = ['user__full_name', 'council_number', 'specialty']


class ScheduleConfigViewSet(viewsets.ModelViewSet):
    queryset = ScheduleConfig.objects.select_related('professional__user').all()
    serializer_class = ScheduleConfigSerializer
    permission_classes = [IsAuthenticated, HasPermission('admin')]


class AppointmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasPermission('schedule.read')]
    serializer_class = AppointmentSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering = ['start_time']

    def get_queryset(self):
        qs = Appointment.objects.select_related(
            'patient', 'professional__user', 'created_by'
        ).filter(start_time__date__gte=timezone.now().date())

        date_param = self.request.query_params.get('date')
        if date_param:
            try:
                d = datetime.strptime(date_param, '%Y-%m-%d').date()
                qs = qs.filter(start_time__date=d)
            except ValueError:
                pass

        professional_id = self.request.query_params.get('professional_id')
        if professional_id:
            qs = qs.filter(professional_id=professional_id)

        return qs

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'update_status'):
            return [IsAuthenticated(), HasPermission('schedule.write')]
        return super().get_permissions()

    def perform_create(self, serializer):
        try:
            appointment = serializer.save(created_by=self.request.user)
        except Exception as exc:
            msg = str(exc)
            if 'TIME_SLOT_UNAVAILABLE' in msg:
                from rest_framework.exceptions import ValidationError as DRFValidationError
                raise DRFValidationError({'start_time': 'TIME_SLOT_UNAVAILABLE'})
            raise
        log_audit(self.request, 'appointment_create', 'Appointment', appointment.id,
                  new_data={'patient': str(appointment.patient_id), 'start_time': str(appointment.start_time)})

    @action(detail=False, methods=['get'])
    def today(self, request):
        today = timezone.now().date()
        qs = Appointment.objects.select_related('patient', 'professional__user').filter(
            start_time__date=today
        ).order_by('start_time')
        return Response(AppointmentSerializer(qs, many=True).data)

    @action(detail=True, methods=['patch'], url_path='status')
    def update_status(self, request, pk=None):
        appointment = self.get_object()
        new_status = request.data.get('status')
        valid = [s[0] for s in Appointment.STATUS_CHOICES]
        if new_status not in valid:
            return Response(
                {'error': {'code': 'INVALID_STATUS', 'message': f'Status deve ser um de: {valid}'}},
                status=400,
            )
        old_status = appointment.status
        appointment.status = new_status
        appointment.save(update_fields=['status', 'updated_at'])
        log_audit(request, 'appointment_status_change', 'Appointment', appointment.id,
                  old_data={'status': old_status}, new_data={'status': new_status})
        return Response(AppointmentSerializer(appointment).data)


class AvailableSlotsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, professional_id):
        date_str = request.query_params.get('date')
        duration = int(request.query_params.get('duration', 30))

        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return Response(
                {'error': {'code': 'INVALID_DATE', 'message': 'Formato: YYYY-MM-DD'}},
                status=400,
            )

        try:
            professional = Professional.objects.get(id=professional_id, is_active=True)
            config = professional.schedule_config
        except Professional.DoesNotExist:
            return Response({'error': {'code': 'NOT_FOUND', 'message': 'Profissional não encontrado'}}, status=404)
        except ScheduleConfig.DoesNotExist:
            return Response({'slots': [], 'message': 'Profissional sem agenda configurada'})

        weekday = target_date.weekday()
        working_days = config.working_days if config.working_days else [0, 1, 2, 3, 4]
        if weekday not in working_days:
            return Response({'slots': [], 'message': 'Profissional não atende neste dia'})

        slots = []
        current = datetime.combine(target_date, config.working_hours_start)
        end = datetime.combine(target_date, config.working_hours_end)
        slot_delta = timedelta(minutes=duration)

        booked = list(Appointment.objects.filter(
            professional=professional,
            start_time__date=target_date,
            status__in=['scheduled', 'confirmed', 'waiting', 'in_progress'],
        ).values_list('start_time', 'end_time'))
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
            slots.append({
                'start': current.isoformat(),
                'end': slot_end.isoformat(),
                'available': is_available and current > now_naive,
            })
            current += slot_delta

        return Response({'date': date_str, 'professional_id': str(professional_id), 'slots': slots})


class WaitingRoomView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.now().date()
        waiting = Appointment.objects.select_related('patient', 'professional__user').filter(
            start_time__date=today,
            status__in=['scheduled', 'confirmed', 'waiting'],
        ).order_by('start_time')
        return Response(AppointmentSerializer(waiting, many=True).data)


# ─── Sprint 4: EMR Core views ─────────────────────────────────────────────────

class EncounterViewSet(viewsets.ModelViewSet):
    """Consultas clínicas — ponto central do EMR"""
    permission_classes = [IsAuthenticated, HasPermission('emr.read')]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering = ['-encounter_date']

    def get_queryset(self):
        qs = Encounter.objects.select_related(
            'patient', 'professional__user', 'appointment',
        ).prefetch_related(
            'soap_note', 'vital_signs', 'documents', 'patient__allergies'
        )

        patient_id = self.request.query_params.get('patient_id')
        if patient_id:
            qs = qs.filter(patient_id=patient_id)

        professional_id = self.request.query_params.get('professional_id')
        if professional_id:
            qs = qs.filter(professional_id=professional_id)

        enc_status = self.request.query_params.get('status')
        if enc_status:
            qs = qs.filter(status=enc_status)

        date_param = self.request.query_params.get('date')
        if date_param:
            try:
                d = datetime.strptime(date_param, '%Y-%m-%d').date()
                qs = qs.filter(encounter_date__date=d)
            except ValueError:
                pass

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return EncounterListSerializer
        return EncounterSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'sign'):
            return [IsAuthenticated(), HasPermission('emr.write')]
        if self.action == 'destroy':
            return [IsAuthenticated(), HasPermission('admin')]
        return super().get_permissions()

    def perform_create(self, serializer):
        encounter = serializer.save()
        # Auto-create empty SOAP note and vital signs
        SOAPNote.objects.get_or_create(encounter=encounter)
        VitalSigns.objects.get_or_create(encounter=encounter)
        log_audit(self.request, 'encounter_create', 'Encounter', encounter.id,
                  new_data={
                      'patient': str(encounter.patient_id),
                      'professional': str(encounter.professional_id),
                      'encounter_date': str(encounter.encounter_date),
                  })

    def perform_update(self, serializer):
        encounter = serializer.save()
        log_audit(self.request, 'encounter_update', 'Encounter', encounter.id)

    @action(detail=True, methods=['post'])
    def sign(self, request, pk=None):
        """POST /encounters/{id}/sign/ — assina a consulta"""
        encounter = self.get_object()
        if encounter.status != 'open':
            return Response(
                {'error': {'code': 'ENCOUNTER_NOT_OPEN', 'message': 'Apenas consultas abertas podem ser assinadas.'}},
                status=400,
            )
        encounter.status = 'signed'
        encounter.save(update_fields=['status', 'updated_at'])
        log_audit(request, 'encounter_sign', 'Encounter', encounter.id,
                  new_data={'status': 'signed', 'signed_by': str(request.user.id)})
        return Response(EncounterSerializer(encounter).data)


class SOAPNoteViewSet(viewsets.ModelViewSet):
    """Notas SOAP — somente PATCH, nunca DELETE"""
    queryset = SOAPNote.objects.select_related('encounter').all()
    serializer_class = SOAPNoteSerializer
    permission_classes = [IsAuthenticated, HasPermission('emr.write')]
    http_method_names = ['get', 'patch', 'head', 'options']

    def perform_update(self, serializer):
        soap = serializer.save()
        log_audit(self.request, 'soap_note_update', 'SOAPNote', soap.id,
                  new_data={
                      'encounter': str(soap.encounter_id),
                      'updated_at': str(soap.updated_at),
                  })


class VitalSignsViewSet(viewsets.ModelViewSet):
    """Sinais vitais"""
    queryset = VitalSigns.objects.select_related('encounter').all()
    serializer_class = VitalSignsSerializer
    permission_classes = [IsAuthenticated, HasPermission('emr.write')]
    http_method_names = ['get', 'patch', 'head', 'options']

    def perform_update(self, serializer):
        vs = serializer.save()
        log_audit(self.request, 'vital_signs_update', 'VitalSigns', vs.id,
                  new_data={'encounter': str(vs.encounter_id)})


class ClinicalDocumentViewSet(viewsets.ModelViewSet):
    """Documentos clínicos — atestado, receita, encaminhamento"""
    queryset = ClinicalDocument.objects.select_related('encounter', 'signed_by').all()
    serializer_class = ClinicalDocumentSerializer
    permission_classes = [IsAuthenticated, HasPermission('emr.write')]
    filter_backends = [DjangoFilterBackend]

    def get_queryset(self):
        qs = super().get_queryset()
        encounter_id = self.request.query_params.get('encounter_id')
        if encounter_id:
            qs = qs.filter(encounter_id=encounter_id)
        return qs

    def perform_create(self, serializer):
        doc = serializer.save()
        log_audit(self.request, 'document_create', 'ClinicalDocument', doc.id,
                  new_data={'doc_type': doc.doc_type, 'encounter': str(doc.encounter_id)})

    @action(detail=True, methods=['post'])
    def sign(self, request, pk=None):
        """POST /documents/{id}/sign/ — assina o documento"""
        doc = self.get_object()
        if doc.is_signed:
            return Response(
                {'error': {'code': 'ALREADY_SIGNED', 'message': 'Documento já está assinado.'}},
                status=400,
            )
        doc.sign(request.user)
        log_audit(request, 'document_sign', 'ClinicalDocument', doc.id,
                  new_data={'signed_by': str(request.user.id), 'signed_at': str(doc.signed_at)})
        return Response(ClinicalDocumentSerializer(doc).data)
