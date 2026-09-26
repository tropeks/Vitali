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

Ordem 022: o laço agora isola falha POR TENANT. Antes, uma clínica cuja folha
do mês corrente não podia ser criada (porque já existe uma linha dela na
DEFAULT do mês — ver ``partitioning.ensure_tenant_partition``) fazia
``IntegrityError`` subir cru e abortava o comando inteiro, deixando sem folha
TODOS os tenants ainda não processados no laço (ordem alfabética por
``schema_name``, então "ainda não processados" é determinístico). Cada
(tenant, mês) agora roda dentro do próprio ``transaction.atomic()``
(savepoint) — sem isso, o ``IntegrityError`` envenena a transação inteira e
nem a query seguinte roda. O comando termina com ``CommandError`` nomeando
cada tenant que falhou e apontando ``backfill_audit_partitions`` (que move as
linhas presas na DEFAULT para a folha dedicada — rodar o comando de novo
depois costuma resolver).
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core import partitioning
from apps.core.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Pré-cria a partição do mês corrente e do seguinte para cada tenant "
        "(idempotente) e alerta se alguma linha estiver em uma folha DEFAULT."
    )

    def handle(self, *args, **options):
        months = partitioning.month_starts(2)
        # order_by("schema_name"): determinístico, não a ordem física da
        # tabela — quem "vem depois no laço" tem que ser previsível para quem
        # lê o log, e não pode mudar de execução pra execução.
        tenants = list(Tenant.objects.exclude(schema_name="public").order_by("schema_name"))

        for month_start in months:
            partitioning.ensure_month_partition(month_start)

        created = 0
        failures: list[tuple[str, str]] = []
        for tenant in tenants:
            for month_start in months:
                error = self._ensure_one_leaf(tenant.schema_name, month_start)
                if error is None:
                    created += 1
                else:
                    failures.append((tenant.schema_name, error))

        self.stdout.write(
            self.style.SUCCESS(
                f"partições garantidas: {len(months)} mês(es) × {len(tenants)} tenant(s) "
                f"= {created} folha(s) dedicada(s) conferida(s)/criada(s)"
            )
        )

        self._warn_on_default_rows()

        if failures:
            detail = "; ".join(f"{schema} ({cause})" for schema, cause in failures)
            raise CommandError(
                f"{len(failures)} tenant(s) sem folha dedicada — provável linha já presa na "
                "folha DEFAULT do mês (rode "
                "apps.core.management.commands.backfill_audit_partitions e execute este "
                f"comando de novo): {detail}"
            )

    def _ensure_one_leaf(self, schema_name: str, month_start) -> str | None:
        """Ensure the dedicated leaf for one (tenant, month). Returns None on
        success, or an error description on failure — never raises: a savepoint
        (``transaction.atomic()``) isolates the failure so it can't poison the
        rest of the loop (see module docstring)."""
        try:
            with transaction.atomic():
                partitioning.ensure_tenant_partition(month_start, schema_name)
        except Exception as exc:  # noqa: BLE001 — isolado por tenant, ver docstring
            logger.error(
                "ensure_audit_partitions: falhou tenant=%s mes=%s-%s err=%s",
                schema_name,
                month_start.year,
                month_start.month,
                exc,
            )
            return f"{month_start.isoformat()}: {exc}"
        return None

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
