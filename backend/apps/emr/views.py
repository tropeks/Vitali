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
from .models import Patient, Allergy, MedicalHistory, Professional, Appointment, ScheduleConfig
from .serializers import (
    PatientSerializer, PatientListSerializer, PatientCreateSerializer,
    AllergySerializer, MedicalHistorySerializer, ProfessionalSerializer,
    AppointmentSerializer, ScheduleConfigSerializer,
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
        # Soft delete
        old_data = {'is_active': True}
        instance.is_active = False
        instance.save()
        log_audit(self.request, 'patient_deactivate', 'Patient', instance.id, old_data=old_data)

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        patient = self.get_object()
        # Placeholder — encounters serão adicionados no Sprint 4
        return Response({
            'patient_id': str(patient.id),
            'events': [],
            'message': 'Timeline disponível no Sprint 4 com encounters clínicos.',
        })

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
                raise DRFValidationError({'start_time': 'TIME_SLOT_UNAVAILABLE: Horário já ocupado para este profissional.'})
            raise
        log_audit(self.request, 'appointment_create', 'Appointment', appointment.id,
                  new_data={'patient': str(appointment.patient_id), 'start_time': str(appointment.start_time)})

    @action(detail=False, methods=['get'])
    def today(self, request):
        today = timezone.now().date()
        qs = Appointment.objects.select_related('patient', 'professional__user').filter(
            start_time__date=today
        ).order_by('start_time')
        serializer = AppointmentSerializer(qs, many=True)
        return Response(serializer.data)

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
    """GET /api/v1/professionals/{professional_id}/available-slots?date=YYYY-MM-DD&duration=30"""
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
            return Response(
                {'error': {'code': 'NOT_FOUND', 'message': 'Profissional não encontrado'}},
                status=404,
            )
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

        # Strip timezone from booked times for naive comparison
        booked_naive = []
        for s, e in booked:
            s_naive = s.replace(tzinfo=None) if s.tzinfo else s
            e_naive = e.replace(tzinfo=None) if e.tzinfo else e
            booked_naive.append((s_naive, e_naive))

        now_naive = timezone.now().replace(tzinfo=None)

        while current + slot_delta <= end:
            slot_end = current + slot_delta
            # Skip lunch break
            if config.lunch_start and config.lunch_end:
                lunch_s = datetime.combine(target_date, config.lunch_start)
                lunch_e = datetime.combine(target_date, config.lunch_end)
                if current < lunch_e and slot_end > lunch_s:
                    current = lunch_e
                    continue
            is_available = not any(
                current < e and slot_end > s for s, e in booked_naive
            )
            slots.append({
                'start': current.isoformat(),
                'end': slot_end.isoformat(),
                'available': is_available and current > now_naive,
            })
            current += slot_delta

        return Response({
            'date': date_str,
            'professional_id': str(professional_id),
            'slots': slots,
        })


class WaitingRoomView(APIView):
    """GET /api/v1/waiting-room — lista de pacientes aguardando hoje"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.now().date()
        waiting = Appointment.objects.select_related('patient', 'professional__user').filter(
            start_time__date=today,
            status__in=['scheduled', 'confirmed', 'waiting'],
        ).order_by('start_time')
        return Response(AppointmentSerializer(waiting, many=True).data)
