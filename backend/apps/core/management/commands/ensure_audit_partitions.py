"""
Management command: ensure_audit_partitions (ordem 021, Emenda do Imediato)

"Não carimbo 20 anos em cima de expurgo inerte." A ordem 020 entregou
``ensure_month_partition``/``ensure_tenant_partition``, mas nada no caminho de
produção jamais os chamava — só um comentário e os testes. Resultado medido em
banco limpo: toda escrita real caía em ``core_auditlog_default_default``, e o
expurgo por tenant (que só derruba a folha DEDICADA) nunca tinha o que
derrubar. A retenção de 20 anos seria decorativa.

Este comando fecha esse buraco: idempotente, pré-cria a partição do MÊS
CORRENTE e do SEGUINTE para cada tenant (as duas funções já existiam — só
ninguém as chamava). Chamado em dois lugares do caminho real:

* pelo script de deploy, logo depois do `migrate_schemas` (ver
  ``scripts/migrate_schemas.sh``) — cobre o boot/primeiro deploy;
* por uma tarefa agendada diária (``core.ensure_audit_partitions``, Celery
  Beat — ver ``apps.core.tasks.ensure_audit_partitions`` e a migration que
  registra o ``PeriodicTask``) — cobre o mês virando sem um deploy no meio.

Deliberadamente NÃO em ``CoreConfig.ready()``: ``ready()`` roda também em
``migrate``, ``makemigrations`` e em todo management command — tocar o banco
ali quebraria a própria migração (a app ainda pode nem ter suas tabelas).

Também funciona como o alarme do item 4 da Emenda: depois de garantir as
partições, relata quantas linhas hoje vivem em alguma folha DEFAULT (a rede de
segurança que nunca pode recusar uma escrita) — a partir de agora, uma
contagem não-zero aqui significa **partição faltando**, não normalidade.
"""

from __future__ import annotations

import datetime
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core import partitioning
from apps.core.models import Tenant

logger = logging.getLogger(__name__)


def _month_starts(count: int, *, today: datetime.date | None = None) -> list[datetime.date]:
    """The first day of *today*'s month, plus the next *count - 1* months."""
    today = today or timezone.now().date()
    months = []
    year, month = today.year, today.month
    for _ in range(count):
        months.append(datetime.date(year, month, 1))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


class Command(BaseCommand):
    help = (
        "Pré-cria a partição do mês corrente e do seguinte para cada tenant "
        "(idempotente) e alerta se alguma linha estiver em uma folha DEFAULT."
    )

    def handle(self, *args, **options):
        months = _month_starts(2)
        tenants = list(Tenant.objects.exclude(schema_name="public"))

        for month_start in months:
            partitioning.ensure_month_partition(month_start)

        created = 0
        for tenant in tenants:
            for month_start in months:
                partitioning.ensure_tenant_partition(month_start, tenant.schema_name)
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"partições garantidas: {len(months)} mês(es) × {len(tenants)} tenant(s) "
                f"= {created} folha(s) dedicada(s) conferida(s)/criada(s)"
            )
        )

        self._warn_on_default_rows()

    def _warn_on_default_rows(self) -> None:
        counts = partitioning.default_leaf_row_counts()
        if not counts:
            self.stdout.write(self.style.SUCCESS("nenhuma linha em folha DEFAULT"))
            return
        total = sum(counts.values())
        logger.warning(
            "core_auditlog: %d linha(s) em folha(s) DEFAULT (partição faltando): %s",
            total,
            counts,
        )
        self.stdout.write(
            self.style.WARNING(
                f"ALERTA: {total} linha(s) em folha(s) DEFAULT — isso significa partição "
                f"faltando, não normalidade: {counts}. Ver "
                "apps.core.management.commands.backfill_audit_partitions."
            )
        )
