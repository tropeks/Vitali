"""Serializers for the telemedicine module."""

from __future__ import annotations

from rest_framework import serializers

from .models import TelemedicineSession


class TelemedicineSessionSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = TelemedicineSession
        fields = [
            "id",
            "appointment",
            "patient",
            "patient_name",
            "professional",
            "room_uid",
            "status",
            "status_display",
            "scheduled_for",
            "started_at",
            "ended_at",
            "duration_seconds",
            "recording_url",
            "notes",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "room_uid",
            "status",
            "status_display",
            "started_at",
            "ended_at",
            "duration_seconds",
            "created_at",
            "created_by",
            "patient_name",
        ]


class TelemedicineSessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelemedicineSession
        fields = ["appointment", "patient", "professional", "scheduled_for", "notes"]


class RecordingUrlSerializer(serializers.Serializer):
    recording_url = serializers.URLField(max_length=500)
