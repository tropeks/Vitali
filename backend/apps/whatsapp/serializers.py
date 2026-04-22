from rest_framework import serializers

from .models import MessageLog, ScheduledReminder, WhatsAppContact


class WhatsAppContactSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True, default=None)

    class Meta:
        model = WhatsAppContact
        fields = [
            "id",
            "phone",
            "patient",
            "patient_name",
            "opt_in",
            "opt_in_at",
            "opt_out_at",
            "created_at",
        ]
        read_only_fields = ["opt_in", "opt_in_at", "opt_out_at", "created_at"]


class MessageLogSerializer(serializers.ModelSerializer):
    contact_phone = serializers.CharField(source="contact.phone", read_only=True)
    patient_name = serializers.CharField(
        source="contact.patient.full_name", read_only=True, default=None
    )

    class Meta:
        model = MessageLog
        fields = [
            "id",
            "contact",
            "contact_phone",
            "patient_name",
            "direction",
            "content_preview",
            "message_type",
            "appointment",
            "created_at",
        ]
        read_only_fields = fields


class ScheduledReminderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduledReminder
        fields = ["id", "appointment", "reminder_type", "status", "sent_at", "created_at"]
        read_only_fields = fields
