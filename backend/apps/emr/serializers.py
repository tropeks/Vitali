import re
from rest_framework import serializers
from .models import Patient, Allergy, MedicalHistory, Professional, Appointment, ScheduleConfig


def validate_cpf(cpf: str) -> str:
    cpf = re.sub(r'\D', '', cpf)
    if len(cpf) != 11 or len(set(cpf)) == 1:
        raise serializers.ValidationError('CPF inválido.')
    for i in range(2):
        total = sum(int(cpf[j]) * (10 + i - j) for j in range(9 + i))
        digit = (total * 10 % 11) % 10
        if digit != int(cpf[9 + i]):
            raise serializers.ValidationError('CPF inválido.')
    return cpf


class AllergySerializer(serializers.ModelSerializer):
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Allergy
        fields = [
            'id', 'substance', 'reaction', 'severity', 'severity_display',
            'status', 'status_display', 'confirmed_by', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class MedicalHistorySerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MedicalHistory
        fields = [
            'id', 'condition', 'cid10_code', 'type', 'type_display',
            'status', 'status_display', 'onset_date', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class PatientListSerializer(serializers.ModelSerializer):
    age = serializers.IntegerField(read_only=True)
    cpf_masked = serializers.SerializerMethodField()
    active_allergies_count = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = [
            'id', 'medical_record_number', 'full_name', 'social_name',
            'birth_date', 'age', 'gender', 'phone', 'whatsapp',
            'cpf_masked', 'is_active', 'active_allergies_count', 'created_at',
        ]

    def get_cpf_masked(self, obj):
        return '***.***.***-**'

    def get_active_allergies_count(self, obj):
        return obj.allergies.filter(status='active').count()


class PatientSerializer(serializers.ModelSerializer):
    age = serializers.IntegerField(read_only=True)
    cpf = serializers.CharField(write_only=True)
    cpf_masked = serializers.SerializerMethodField(read_only=True)
    allergies = AllergySerializer(many=True, read_only=True)
    medical_history = MedicalHistorySerializer(many=True, read_only=True)
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)

    class Meta:
        model = Patient
        fields = [
            'id', 'medical_record_number', 'full_name', 'social_name',
            'cpf', 'cpf_masked', 'birth_date', 'age', 'gender', 'gender_display',
            'blood_type', 'phone', 'whatsapp', 'email',
            'address', 'insurance_data', 'emergency_contact',
            'photo_url', 'notes', 'is_active',
            'allergies', 'medical_history',
            'created_at', 'updated_at', 'created_by',
        ]
        read_only_fields = ['id', 'medical_record_number', 'created_at', 'updated_at', 'created_by']

    def get_cpf_masked(self, obj):
        return '***.***.***-**'

    def validate_cpf(self, value):
        return validate_cpf(value)


class PatientCreateSerializer(PatientSerializer):
    class Meta(PatientSerializer.Meta):
        fields = [f for f in PatientSerializer.Meta.fields
                  if f not in ('allergies', 'medical_history', 'cpf_masked')]


class ProfessionalSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    council_type_display = serializers.CharField(source='get_council_type_display', read_only=True)

    class Meta:
        model = Professional
        fields = [
            'id', 'user', 'user_name', 'user_email',
            'council_type', 'council_type_display', 'council_number', 'council_state',
            'specialty', 'cbo_code', 'cnes_code', 'is_active', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class ScheduleConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleConfig
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class AppointmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.full_name', read_only=True)
    patient_mrn = serializers.CharField(source='patient.medical_record_number', read_only=True)
    professional_name = serializers.CharField(source='professional.user.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    duration_minutes = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            'id', 'patient', 'patient_name', 'patient_mrn',
            'professional', 'professional_name',
            'start_time', 'end_time', 'duration_minutes',
            'type', 'type_display', 'status', 'status_display',
            'source', 'notes', 'whatsapp_reminder_sent', 'whatsapp_confirmed',
            'cancellation_reason', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_duration_minutes(self, obj):
        delta = obj.end_time - obj.start_time
        return int(delta.total_seconds() / 60)

    def validate(self, data):
        if data.get('end_time') and data.get('start_time'):
            if data['end_time'] <= data['start_time']:
                raise serializers.ValidationError({'end_time': 'Horário de fim deve ser após o início.'})
        return data
