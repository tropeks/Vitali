"""
H4 — DRF serializers for the checagem/administração + reação transfusional surface.

Both projections are read-only over the wire: :class:`TransfusionAdministration`
rows are created only through the ``checar`` action (never a plain POST), and
:class:`TransfusionReaction` rows only through the ``reacao`` action — both are
append-only.
"""

from __future__ import annotations

from rest_framework import serializers

from .transfusion_admin_models import TransfusionAdministration, TransfusionReaction


class TransfusionAdministrationSerializer(serializers.ModelSerializer):
    bag_identifier = serializers.CharField(source="bag.identifier", read_only=True)

    class Meta:
        model = TransfusionAdministration
        fields = [
            "id",
            "request",
            "bag",
            "bag_identifier",
            "patient",
            "administered_by",
            "witness",
            "started_at",
            "finished_at",
            "volume_ml",
            "status",
            "patient_barcode_scanned",
            "bag_barcode_scanned",
            "checagem_verified",
            "checagem_override_reason",
            "created_at",
        ]
        read_only_fields = fields


class TransfusionReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransfusionReaction
        fields = [
            "id",
            "administration",
            "request",
            "tipo",
            "gravidade",
            "descricao",
            "conduta",
            "notificado_hemovigilancia",
            "occurred_at",
            "recorded_by",
            "created_at",
        ]
        read_only_fields = fields
