"""
Management command: purge_audit_logs (ordem 020, emenda do Capitão; ordem 021,
retenção de 20 anos por tenant)

Expurgo de ``core_auditlog`` por partição de mês, nunca por ``DELETE``. Desde
a emenda do Capitão, o ``DROP PARTITION`` é o ÚLTIMO passo de uma sequência —
não o único: exporta -> checksum do claro -> cifra (gpg, mesma chave do
``scripts/backup.sh``) -> decifra e confere localmente contra a partição viva,
linha a linha -> só então guarda o artefato -> só então dropa (ver
apps.core.cold_storage e apps.core.partitioning.drop_partition, que RECUSA
rodar sem um recibo de exportação verificado para a MESMA partição).

Ordem 021 move prazo e permissão do nível global para o nível de tenant:

* não existe mais um "liga geral" (``AUDIT_LOG_PURGE_ENABLED`` /
  ``AUDIT_LOG_RETENTION_DAYS``, ambos aposentados por esta ordem — ver
  ``apps.core.models.TenantAuditRetention``). Cada tenant tem seu próprio
  ``retention_months`` e ``purge_enabled``; um tenant SEM linha configurada
  usa o default de fábrica do próprio model (240 meses, expurgo desligado) —
  nunca apaga por omissão;
* ``--dry-run`` é o padrão: sem ``--execute`` explícito, relata e sai 0 sem
  tocar em nada;
* ``--schema NAME`` restringe a varredura a um único tenant; sem isso, varre
  TODOS os tenants, cada um com seu próprio prazo/permissão. Em qualquer dos
  dois casos, só a partição LIST DEDICADA daquele tenant (ver
  apps.core.partitioning.ensure_tenant_partition) é candidata a DROP — a
  partição DEFAULT (mês ou top-level), que pode conter linhas de outros
  tenants, nunca é tocada por este comando. Um tenant sem partição dedicada
  simplesmente não tem nada a expurgar por aqui: suas linhas, se houver,
  ficam na DEFAULT compartilhada indefinidamente (não há mais um "expurgo
  global do mês" — com retenção por tenant, dropar a partição do mês inteiro
  deixou de ser seguro, porque tenants diferentes na mesma DEFAULT podem ter
  prazos diferentes).

Uso:
    python manage.py purge_audit_logs                        # dry-run, todos os tenants
    python manage.py purge_audit_logs --execute               # expurgo real, todos os tenants
    python manage.py purge_audit_logs --execute --schema acme # só o tenant acme
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core import cold_storage, partitioning
from apps.core.models import Tenant, TenantAuditRetention


@dataclass(frozen=True)
class _Retention:
    retention_months: int
    purge_enabled: bool
    configured: bool  # False => tenant has no TenantAuditRetention row (factory default)


def _resolve_retention(tenant: Tenant) -> _Retention:
    """The per-tenant deadline+permission pair ordem 021 asks for.

    A tenant without a ``TenantAuditRetention`` row is resolved to that
    model's OWN field defaults (not a duplicated constant here), so the
    command can never drift from what a freshly-created row would read.
    """
    config = TenantAuditRetention.objects.filter(tenant=tenant).first()
    if config is not None:
        return _Retention(config.retention_months, config.purge_enabled, configured=True)
    fields = TenantAuditRetention._meta
    return _Retention(
        retention_months=fields.get_field("retention_months").default,
        purge_enabled=fields.get_field("purge_enabled").default,
        configured=False,
    )


class Command(BaseCommand):
    help = (
        "Expurga partições dedicadas de core_auditlog fora da janela de retenção "
        "de cada tenant (DROP, nunca DELETE)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Executa o expurgo de verdade. Sem esta flag, é dry-run (o padrão).",
        )
        parser.add_argument(
            "--schema",
            default=None,
            help="Restringe a varredura a um único tenant (por schema_name).",
        )

    def handle(self, *args, **options):
        execute = options["execute"]
        now = timezone.now()
        for tenant in self._resolve_tenants(options["schema"]):
            self._handle_tenant(tenant, now=now, execute=execute)

        if not execute:
            self.stdout.write(
                self.style.WARNING("dry-run: nada foi tocado. Use --execute para aplicar.")
            )

    def _resolve_tenants(self, schema: str | None) -> list[Tenant]:
        if schema:
            try:
                return [Tenant.objects.get(schema_name=schema)]
            except Tenant.DoesNotExist as exc:
                raise CommandError(f"nenhum tenant com schema_name={schema!r}") from exc
        return list(Tenant.objects.order_by("schema_name"))

    def _handle_tenant(self, tenant: Tenant, *, now, execute: bool) -> None:
        retention = _resolve_retention(tenant)
        if not retention.purge_enabled:
            reason = (
                "TenantAuditRetention.purge_enabled=False"
                if retention.configured
                else "sem TenantAuditRetention — default de fábrica é reter"
            )
            self.stdout.write(f"{tenant.schema_name}: expurgo desligado ({reason}) — nada a fazer")
            return

        cutoff = partitioning.retention_cutoff(now, retention.retention_months)
        expired = [m for m in partitioning.list_month_partitions() if m.is_expired(cutoff)]
        if not expired:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{tenant.schema_name}: nada além dos {retention.retention_months} meses "
                    f"(cutoff={cutoff.isoformat()})"
                )
            )
            return

        for month in expired:
            self._handle_tenant_month(tenant, month, execute=execute)

    def _handle_tenant_month(
        self, tenant: Tenant, month: partitioning.MonthPartition, *, execute: bool
    ) -> None:
        leaf = partitioning.tenant_partition_name(month.name, tenant.schema_name)
        if not partitioning.partition_exists(leaf):
            self.stdout.write(
                f"· {tenant.schema_name}: sem partição dedicada em {month.name} — nada a fazer "
                "(linhas desse tenant, se houver, estão na DEFAULT compartilhada com outros "
                "tenants e este comando nunca toca a DEFAULT)"
            )
            return

        row_count = partitioning.partition_row_count(leaf)
        label = f"{leaf} ({row_count} linha(s), mês {month.year}-{month.month:02d}, tenant={tenant.schema_name})"
        if not execute:
            self.stdout.write(f"[dry-run] removeria {label}")
            return
        self._purge_one(leaf, label)

    def _purge_one(self, target: str, label: str) -> None:
        try:
            receipt = cold_storage.export_and_verify_partition(target)
        except cold_storage.ColdExportError as exc:
            self.stderr.write(self.style.ERROR(f"recusando dropar {label}: {exc}"))
            return
        try:
            partitioning.drop_partition(target, cold_export_receipt=receipt)
        except partitioning.PartitioningError as exc:
            self.stderr.write(self.style.ERROR(f"recusando dropar {label}: {exc}"))
            return
        self.stdout.write(
            self.style.SUCCESS(f"removido {label} — cópia fria em {receipt.stored_location}")
        )
