"""
Management command: purge_audit_logs (ordem 020, com a emenda do Capitão)

Expurgo de ``core_auditlog`` por partição de mês, nunca por ``DELETE``. Desde
a emenda do Capitão, o ``DROP PARTITION`` é o ÚLTIMO passo de uma sequência —
não o único: exporta -> checksum do claro -> cifra (gpg, mesma chave do
``scripts/backup.sh``) -> decifra e confere localmente contra a partição viva,
linha a linha -> só então guarda o artefato -> só então dropa (ver
apps.core.cold_storage e apps.core.partitioning.drop_partition, que RECUSA
rodar sem um recibo de exportação verificado para a MESMA partição).

Três travas, em código, não em documento:

* recusa rodar sem AMBAS ``AUDIT_LOG_PURGE_ENABLED=True`` e
  ``AUDIT_LOG_RETENTION_DAYS`` preenchido — nomeando o que falta;
* ``--dry-run`` é o padrão: sem ``--execute`` explícito, relata e sai 0 sem
  tocar em nada;
* ``--schema NAME`` restringe a DROP a uma partição dedicada daquele tenant
  (se existir uma — ver apps.core.partitioning.ensure_tenant_partition), sem
  nunca tocar a partição DEFAULT compartilhada, que pode conter outros
  tenants. Sem ``--schema``, o expurgo é global: dropa o mês inteiro (RANGE),
  que já é seguro por tenant nenhum tenant tem dado fora da janela ali dentro
  antes do limite do mês.

Uso:
    python manage.py purge_audit_logs                     # dry-run (padrão)
    python manage.py purge_audit_logs --execute            # expurgo global real
    python manage.py purge_audit_logs --execute --schema acme  # só o tenant acme
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core import cold_storage, partitioning


class Command(BaseCommand):
    help = "Expurga partições de core_auditlog fora da janela de retenção (DROP, nunca DELETE)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Executa o expurgo de verdade. Sem esta flag, é dry-run (o padrão).",
        )
        parser.add_argument(
            "--schema",
            default=None,
            help="Restringe a uma partição dedicada deste tenant (nunca à DEFAULT compartilhada).",
        )

    def handle(self, *args, **options):
        retention_days = self._check_settings()
        cutoff = timezone.now() - timedelta(days=retention_days)
        expired = [m for m in partitioning.list_month_partitions() if m.is_expired(cutoff)]

        if not expired:
            self.stdout.write(
                self.style.SUCCESS(f"nada fora da janela (cutoff={cutoff.isoformat()})")
            )
            return

        schema = options["schema"]
        execute = options["execute"]
        for month in expired:
            target, row_count = self._resolve_target(month, schema)
            if target is None:
                continue
            label = f"{target} ({row_count} linha(s), mês {month.year}-{month.month:02d})"
            if not execute:
                self.stdout.write(f"[dry-run] removeria {label}")
                continue
            self._purge_one(target, label)

        if not execute:
            self.stdout.write(
                self.style.WARNING("dry-run: nada foi tocado. Use --execute para aplicar.")
            )

    def _check_settings(self) -> int:
        retention_days = getattr(settings, "AUDIT_LOG_RETENTION_DAYS", None)
        purge_enabled = getattr(settings, "AUDIT_LOG_PURGE_ENABLED", False)
        missing = []
        if not purge_enabled:
            missing.append("AUDIT_LOG_PURGE_ENABLED=True")
        if retention_days is None:
            missing.append("AUDIT_LOG_RETENTION_DAYS=<dias>")
        if missing:
            raise CommandError(
                "purge_audit_logs recusa rodar: falta configurar " + " e ".join(missing) + ". "
                "O padrão de fábrica é reter, não expurgar (ordem 020) — "
                "ambas as configurações têm de ser definidas deliberadamente."
            )
        assert retention_days is not None  # narrowed by the check above
        return int(retention_days)

    def _resolve_target(
        self, month: partitioning.MonthPartition, schema: str | None
    ) -> tuple[str | None, int]:
        if schema:
            leaf = partitioning.tenant_partition_name(month.name, schema)
            if not partitioning.partition_exists(leaf):
                self.stdout.write(
                    f"· sem partição dedicada para schema={schema!r} em {month.name} — nada a fazer "
                    "(as linhas desse tenant, se houver, estão na DEFAULT compartilhada e aguardam "
                    "o expurgo global daquele mês)"
                )
                return None, 0
            return leaf, partitioning.partition_row_count(leaf)
        return month.name, partitioning.partition_row_count(month.name)

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
