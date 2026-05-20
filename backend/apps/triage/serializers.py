"""Serializers for the triage REST surface."""

from __future__ import annotations

from rest_framework import serializers

from .models import TriageSession
from .services.question_bank import RED_FLAG_QUESTIONS


class TriageQuestionSerializer(serializers.Serializer):
    key = serializers.CharField()
    prompt = serializers.CharField()
    yes_is_red_flag = serializers.BooleanField()


class TriageSessionSerializer(serializers.ModelSerializer):
    next_question = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    urgency_display = serializers.CharField(source="get_urgency_display", read_only=True)

    class Meta:
        model = TriageSession
        fields = [
            "id",
            "patient",
            "contact_phone",
            "chief_complaint",
            "answers",
            "status",
            "status_display",
            "urgency",
            "urgency_display",
            "rationale",
            "matched_keywords",
            "red_flags_positive",
            "next_question",
            "started_at",
            "evaluated_at",
            "escalated_at",
            "closed_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "urgency",
            "urgency_display",
            "rationale",
            "matched_keywords",
            "red_flags_positive",
            "next_question",
            "started_at",
            "evaluated_at",
            "escalated_at",
            "closed_at",
            "created_by",
        ]

    def get_next_question(self, obj: TriageSession) -> dict | None:
        q = obj.current_question()
        if q is None:
            return None
        return TriageQuestionSerializer(q).data


class TriageSessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TriageSession
        fields = ["patient", "contact_phone", "chief_complaint"]


class TriageAnswerSerializer(serializers.Serializer):
    key = serializers.ChoiceField(choices=[q.key for q in RED_FLAG_QUESTIONS])
    value = serializers.CharField(max_length=20)


class TriageChiefComplaintSerializer(serializers.Serializer):
    chief_complaint = serializers.CharField(max_length=2000)
