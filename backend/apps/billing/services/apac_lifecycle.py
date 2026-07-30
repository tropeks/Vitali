"""
APAC-simetria — Ciclo de vida / reconciliação da APAC (S3).
===========================================================
Espelho ambulatorial de :mod:`apps.billing.services.aih_lifecycle`: a APAC nasce
``solicitada`` e é reconciliada (``autorizada``) com o número oficial de 13
dígitos do gestor SUS (preservando o número anterior), ou glosada (``rejeitada``).
Toda transição passa por aqui (nunca por ``serializer.save`` cru) dentro de uma
``transaction.atomic`` para manter número, situação e histórico consistentes.
"""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.billing.sus_models import ApacAutorizacao

#: Número oficial da APAC: exatamente 13 dígitos (padrão do gestor SUS).
_NUMERO_OFICIAL_RE = re.compile(r"^\d{13}$")


@transaction.atomic
def reconciliar_numero_oficial(
    *,
    apac: ApacAutorizacao,
    numero_oficial: str,
    professional_solicitante: Any | None = None,
    data_autorizacao: Any | None = None,
    actor: Any | None = None,
) -> ApacAutorizacao:
    """Reconcilia a APAC com o número oficial do gestor: solicitada/rejeitada →
    autorizada, substituindo o número pelo oficial (13 dígitos) e preservando o
    anterior em ``numero_provisorio`` — atomicamente.

    Levanta ``ValidationError`` se o número não tiver 13 dígitos, já pertencer a
    outra APAC, ou se a APAC já estiver ``autorizada``.
    """
    numero = (numero_oficial or "").strip()
    if not _NUMERO_OFICIAL_RE.match(numero):
        raise ValidationError("Número oficial da APAC deve ter exatamente 13 dígitos.")

    locked = ApacAutorizacao.objects.select_for_update().get(pk=apac.pk)
    if locked.situacao == ApacAutorizacao.Situacao.AUTORIZADA:
        raise ValidationError("APAC já está autorizada; não pode ser reconciliada novamente.")
    if ApacAutorizacao.objects.exclude(pk=locked.pk).filter(numero_apac=numero).exists():
        raise ValidationError(f"Número oficial {numero} já pertence a outra APAC.")

    if not locked.numero_provisorio:
        locked.numero_provisorio = locked.numero_apac
    locked.numero_apac = numero
    locked.situacao = ApacAutorizacao.Situacao.AUTORIZADA
    locked.data_autorizacao = data_autorizacao or timezone.now().date()
    locked.motivo_rejeicao = ""
    if professional_solicitante is not None:
        locked.professional_solicitante = professional_solicitante
    locked.save(
        update_fields=[
            "numero_apac",
            "numero_provisorio",
            "situacao",
            "data_autorizacao",
            "motivo_rejeicao",
            "professional_solicitante",
        ]
    )
    return locked


@transaction.atomic
def rejeitar_apac(
    *, apac: ApacAutorizacao, motivo: str, actor: Any | None = None
) -> ApacAutorizacao:
    """Marca a APAC como ``rejeitada`` (glosa do gestor) com motivo obrigatório —
    atomicamente. Levanta ``ValidationError`` se o motivo for vazio."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Motivo da rejeição é obrigatório.")

    locked = ApacAutorizacao.objects.select_for_update().get(pk=apac.pk)
    locked.situacao = ApacAutorizacao.Situacao.REJEITADA
    locked.motivo_rejeicao = motivo
    locked.save(update_fields=["situacao", "motivo_rejeicao"])
    return locked
