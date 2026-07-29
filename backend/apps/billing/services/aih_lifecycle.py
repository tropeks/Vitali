"""
AI-R1 — Ciclo de vida / reconciliação da AIH (SISAIH).
======================================================
O bridge AI2 (:mod:`apps.billing.services.aih_billing`) cria a AIH com um número
**provisório interno** e situação ``solicitada``. Quando o gestor SUS devolve a
autorização, o hospital reconcilia: o número oficial de 13 dígitos substitui o
provisório (preservado para rastreabilidade), a situação vira ``autorizada`` e o
profissional solicitante pode ser preenchido. Uma AIH glosada vira ``rejeitada``.

Toda transição passa por aqui (nunca por ``serializer.save`` cru) para manter o
número, a situação e o histórico consistentes dentro de uma ``transaction.atomic``.
A remessa SISAIH (AI3) consome ``numero_aih`` cru — reconciliar aqui é o que faz o
número na remessa ser o oficial.
"""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.billing.sus_models import AihAutorizacao

#: Número oficial da AIH: exatamente 13 dígitos (padrão SISAIH do gestor SUS).
_NUMERO_OFICIAL_RE = re.compile(r"^\d{13}$")


@transaction.atomic
def reconciliar_numero_oficial(
    *,
    aih: AihAutorizacao,
    numero_oficial: str,
    professional_solicitante: Any | None = None,
    data_autorizacao: Any | None = None,
    actor: Any | None = None,
) -> AihAutorizacao:
    """Reconcilia a AIH com o número oficial do gestor: solicitada/rejeitada →
    autorizada, substituindo o número provisório pelo oficial (13 dígitos) e
    preservando o provisório em ``numero_provisorio`` — atomicamente.

    Levanta ``ValidationError`` se o número não tiver 13 dígitos, já pertencer a
    outra AIH, ou se a AIH já estiver ``autorizada`` (evita re-autorizar sem
    querer). ``professional_solicitante`` opcional popula o solicitante (o bridge
    AI2 nunca o preenche). ``data_autorizacao`` ausente assume hoje.
    """
    numero = (numero_oficial or "").strip()
    if not _NUMERO_OFICIAL_RE.match(numero):
        raise ValidationError("Número oficial da AIH deve ter exatamente 13 dígitos.")

    locked = AihAutorizacao.objects.select_for_update().get(pk=aih.pk)
    if locked.situacao == AihAutorizacao.Situacao.AUTORIZADA:
        raise ValidationError("AIH já está autorizada; não pode ser reconciliada novamente.")
    if AihAutorizacao.objects.exclude(pk=locked.pk).filter(numero_aih=numero).exists():
        raise ValidationError(f"Número oficial {numero} já pertence a outra AIH.")

    # Preserva o provisório original apenas na primeira reconciliação.
    if not locked.numero_provisorio:
        locked.numero_provisorio = locked.numero_aih
    locked.numero_aih = numero
    locked.situacao = AihAutorizacao.Situacao.AUTORIZADA
    locked.data_autorizacao = data_autorizacao or timezone.now().date()
    locked.motivo_rejeicao = ""
    if professional_solicitante is not None:
        locked.professional_solicitante = professional_solicitante
    locked.save(
        update_fields=[
            "numero_aih",
            "numero_provisorio",
            "situacao",
            "data_autorizacao",
            "motivo_rejeicao",
            "professional_solicitante",
        ]
    )
    return locked


@transaction.atomic
def rejeitar_aih(*, aih: AihAutorizacao, motivo: str, actor: Any | None = None) -> AihAutorizacao:
    """Marca a AIH como ``rejeitada`` (glosa do gestor) com um motivo obrigatório
    — atomicamente. Levanta ``ValidationError`` se o motivo for vazio."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Motivo da rejeição é obrigatório.")

    locked = AihAutorizacao.objects.select_for_update().get(pk=aih.pk)
    locked.situacao = AihAutorizacao.Situacao.REJEITADA
    locked.motivo_rejeicao = motivo
    locked.save(update_fields=["situacao", "motivo_rejeicao"])
    return locked
