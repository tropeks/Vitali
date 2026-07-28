"""
SIGTAP catalog serializer (Sprint S1)
=====================================
Read/write serializer for the SHARED governed SIGTAP catalog
(``SIGTAPProcedure``). Surfaced through the tenant-facing API and gated by the
``sus.read`` / ``sus.write`` role permissions (see ``apps.core.views_sigtap``).
The catalog lives in the public schema; write verbs are governance operations,
not per-tenant clinical data.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.core.sigtap_catalog_models import SIGTAPProcedure


class SIGTAPProcedureSerializer(serializers.ModelSerializer):
    valor_total = serializers.SerializerMethodField()

    class Meta:
        model = SIGTAPProcedure
        fields = [
            "id",
            "code",
            "display",
            "system",
            "version",
            "active",
            "valor_sa",
            "valor_sh",
            "valor_sp",
            "valor_total",
            "competencia_vigencia",
            "instrumento_registro",
            "complexidade",
            "financiamento",
            "sexo_permitido",
            "idade_min_dias",
            "idade_max_dias",
        ]
        read_only_fields = ["id", "system", "valor_total"]

    def get_valor_total(self, obj) -> str:
        return str(obj.valor_total())
