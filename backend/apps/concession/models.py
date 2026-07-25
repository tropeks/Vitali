"""Comodato & Suprimentos de Diagnóstico — módulo tier-gated (diagnostic_concession).

Integra a capacidade do TCX (outsourcing all-inclusive de imagem) no Vitali.
Reusa pharmacy (insumo/estoque), organization (Facility/unidade), imaging (exame),
billing (DRE) e core.FeatureFlag (o tier). Cada sprint adiciona seus modelos num
arquivo dedicado importado no fim deste arquivo (mantém o merge de fan-out trivial).
"""

from django.db import models


class ConcessionService(models.Model):
    """Catálogo local de serviços/exames do módulo de concessão (o que um
    equipamento habilita, o que uma receita consome, o que um preço tarifa).

    Tenant-local (mesmo schema do módulo) para evitar FK cross-schema; um
    ``tuss_code`` opcional amarra ao catálogo TUSS governado do M0 quando útil.
    """

    code = models.CharField("Código", max_length=40, db_index=True)
    name = models.CharField("Nome", max_length=200)
    modality = models.CharField("Modalidade/categoria", max_length=60, blank=True)
    tuss_code = models.CharField("TUSS (opcional)", max_length=20, blank=True)
    active = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["code"], name="concession_service_code_unique"),
        ]
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} — {self.name}"


# Sprint model modules (defined after ConcessionService so their imports resolve).
from .asset_models import *  # noqa: E402,F401,F403
from .contract_models import *  # noqa: E402,F401,F403
from .logistics_models import *  # noqa: E402,F401,F403
from .pnl_models import *  # noqa: E402,F401,F403
