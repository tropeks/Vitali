from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone

from apps.core.permissions import HasPermission
from apps.core.models import AuditLog
from .models import Patient, Allergy, MedicalHistory, Professional
from .serializers import (
    PatientSerializer, PatientListSerializer, PatientCreateSerializer,
    AllergySerializer, MedicalHistorySerializer, ProfessionalSerializer,
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
