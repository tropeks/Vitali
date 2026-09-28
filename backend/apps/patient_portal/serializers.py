"""Serializers for the patient portal module."""

from __future__ import annotations

from rest_framework import serializers

from apps.emr.models import Allergy, Appointment, Encounter, Patient, Prescription

from .models import PatientPortalAccess, PatientRepresentative, PortalConsent


class PatientRepresentativeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientRepresentative
        fields = [
            "id",
            "patient",
            "representative",
            "relationship",
            "active",
            "expires_at",
            "granted_at",
            "revoked_at",
        ]
        read_only_fields = ["id", "granted_at", "revoked_at"]


class PortalConsentSerializer(serializers.ModelSerializer):
    valid = serializers.SerializerMethodField()

    class Meta:
        model = PortalConsent
        fields = [
            "id",
            "patient",
            "granted_by",
            "purpose",
            "policy_version",
            "granted_at",
            "expires_at",
            "revoked_at",
            "valid",
        ]
        read_only_fields = ["id", "granted_by", "granted_at", "revoked_at", "valid"]

    def get_valid(self, obj):
        return obj.is_valid()


class PatientPortalAccessSerializer(serializers.ModelSerializer):
    """Leitura do acesso ao portal: status do convite, nunca a credencial.

    ``invite_token`` é o segredo do link de ativação e fica de fora (ordem
    031): lista, detalhe, revoke e activate não precisam dele, e quem só tem
    ``users.read`` não deve ver a credencial de todo convite aberto. O token sai
    uma vez, no 201 do convite, por ``PatientPortalInviteSerializer``.
    """

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)

    class Meta:
        model = PatientPortalAccess
        fields = [
            "id",
            "user",
            "patient",
            "patient_name",
            "status",
            "status_display",
            "invite_expires_at",
            "invited_at",
            "activated_at",
            "revoked_at",
            "last_seen_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "invite_expires_at",
            "invited_at",
            "activated_at",
            "revoked_at",
            "last_seen_at",
            "patient_name",
        ]


class PatientPortalInviteSerializer(PatientPortalAccessSerializer):
    """Resposta do convite recém-criado: a única que devolve ``invite_token``.

    Vai para quem tem ``users.write`` e acabou de convidar. É a saída manual
    quando ``deliver_portal_invite`` não entrega por nenhum canal (fail-open):
    como chave de API, mostrada uma vez, na criação.
    """

    # Not a model field since order 033 (the database keeps only the hash): the
    # plaintext lives on the instance that minted it, which is the one the
    # create view serializes.
    invite_token = serializers.CharField(read_only=True)

    class Meta(PatientPortalAccessSerializer.Meta):
        fields = [*PatientPortalAccessSerializer.Meta.fields, "invite_token"]


class PatientPortalAccessCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientPortalAccess
        fields = ["user", "patient"]


# ─── Self-data serializers ────────────────────────────────────────────────────


class PortalPatientSerializer(serializers.ModelSerializer):
    """Read-only Patient view the portal user sees about themselves."""

    age = serializers.IntegerField(read_only=True)

    class Meta:
        model = Patient
        fields = [
            "id",
            "full_name",
            "social_name",
            "birth_date",
            "age",
            "gender",
            "blood_type",
            "phone",
            "whatsapp",
            "email",
            "medical_record_number",
        ]
        read_only_fields = fields


class PortalAppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = [
            "id",
            "start_time",
            "end_time",
            "status",
            "type",
            "professional",
            "created_at",
        ]
        read_only_fields = fields


class PortalEncounterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Encounter
        fields = [
            "id",
            "encounter_date",
            "status",
            "chief_complaint",
            "professional",
            "signed_at",
        ]
        read_only_fields = fields


class PortalPrescriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prescription
        fields = ["id", "encounter", "status", "signed_at", "notes", "created_at"]
        read_only_fields = fields


class PortalAllergySerializer(serializers.ModelSerializer):
    class Meta:
        model = Allergy
        fields = ["id", "substance", "reaction", "severity", "status", "created_at"]
        read_only_fields = fields
