"""
H3 — DRF serializers for the requisição transfusional surface.

* :class:`TransfusionRequestSerializer` — the médico's order. ``component`` is
  writable by pk (governed SHARED catalog) with read-only display convenience;
  ``requester``/``patient`` writable by pk. ``status``/``created_by`` are
  server-managed (the reservation state machine lives in the service, not the
  serializer).
* :class:`CrossMatchSerializer` — read-only projection of a compatibility test,
  exposing the derived ``compativel`` flag.
"""

from __future__ import annotations

from rest_framework import serializers

from .transfusion_models import CrossMatch, TransfusionRequest


class CrossMatchSerializer(serializers.ModelSerializer):
    compativel = serializers.BooleanField(read_only=True)
    bag_identifier = serializers.CharField(source="bag.identifier", read_only=True)

    class Meta:
        model = CrossMatch
        fields = [
            "id",
            "request",
            "bag",
            "bag_identifier",
            "abo_compativel",
            "rh_compativel",
            "crossmatch_resultado",
            "compativel",
            "tested_at",
            "tested_by",
            "notes",
        ]
        read_only_fields = fields


class TransfusionRequestSerializer(serializers.ModelSerializer):
    component_display = serializers.CharField(source="component.display", read_only=True)
    component_code = serializers.CharField(source="component.code", read_only=True)
    crossmatches = CrossMatchSerializer(many=True, read_only=True)

    class Meta:
        model = TransfusionRequest
        fields = [
            "id",
            "patient",
            "encounter",
            "admission",
            "surgical_case",
            "emergency_encounter",
            "component",
            "component_code",
            "component_display",
            "quantidade",
            "indicacao",
            "cid",
            "urgencia",
            "requester",
            "status",
            "crossmatches",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "created_by", "created_at", "updated_at"]

    def validate(self, attrs):
        # Mirror the model's clean(): at least one order parent must be set.
        instance = getattr(self, "instance", None)

        def _resolve(field):
            if field in attrs:
                return attrs[field]
            return getattr(instance, field, None) if instance else None

        parents = [
            _resolve("encounter"),
            _resolve("admission"),
            _resolve("surgical_case"),
            _resolve("emergency_encounter"),
        ]
        if not any(parents):
            raise serializers.ValidationError(
                "A requisição precisa de ao menos um vínculo (atendimento, "
                "internação, caso cirúrgico ou boletim de emergência)."
            )
        return attrs
