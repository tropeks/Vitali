"""
H2 — DRF serializers for doador + triagem sorológica.

  * :class:`BloodDonorSerializer` — the tenant blood donor cadastro.
  * :class:`BloodBagSerologySerializer` — read/write for a bag's RDC 34 panel;
    the writable ``bag`` PK + marker fields feed
    :func:`apps.emr.services.blood_serology.registrar_sorologia` (the viewset
    routes create through the service — the state transition is never a raw save).
"""

from __future__ import annotations

from rest_framework import serializers

from .blood_donor_models import BloodBagSerology, BloodDonor


class BloodDonorSerializer(serializers.ModelSerializer):
    class Meta:
        model = BloodDonor
        fields = [
            "id",
            "full_name",
            "cpf",
            "abo",
            "rh_factor",
            "birth_date",
            "last_donation",
            "apto",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class BloodBagSerologySerializer(serializers.ModelSerializer):
    all_non_reactive = serializers.BooleanField(read_only=True)

    class Meta:
        model = BloodBagSerology
        fields = [
            "id",
            "bag",
            "hiv",
            "hbsag",
            "anti_hbc",
            "anti_hcv",
            "sifilis",
            "chagas",
            "htlv",
            "all_non_reactive",
            "tested_at",
            "tested_by",
            "notes",
        ]
        read_only_fields = ["id", "all_non_reactive", "tested_at", "tested_by"]
