"""
Management command: backfill_audit_partitions (ordem 021, Emenda do Imediato)

Moves ``core_auditlog`` rows already sitting in a DEFAULT leaf into the
dedicated month/tenant partitions ``ensure_audit_partitions`` would have
created for them had it been running from day one. One-time (or occasional —
idempotent, safe to re-run) catch-up; ``ensure_audit_partitions`` is what
keeps NEW writes out of DEFAULT going forward.

``--dry-run`` (the default) reports every pending group — (month) for the
top-level DEFAULT, (month, tenant) for each month's own DEFAULT — with row
counts, and touches nothing. ``--execute`` runs it for real, one transaction
per group, and reports the row count and elapsed time actually measured for
each (see apps.core.audit_partition_backfill for why one transaction per
group, not one for the whole table).

See docs/adr/ADR-0001-retencao-auditoria-20-anos.md for the lock-scope plan
this command implements, and why "hoje são poucas linhas" does not mean this
is safe to run unbatched against a live clinic with many.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core import audit_partition_backfill as backfill


class Command(BaseCommand):
    help = (
        "Move linhas de core_auditlog que estao em uma folha DEFAULT para suas "
        "particoes dedicadas (mes e tenant). Idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Executa de verdade. Sem esta flag, e dry-run (o padrao): so relata.",
        )

    def handle(self, *args, **options):
        execute = options["execute"]
        results = backfill.backfill_all(execute=execute)

        if not results:
            self.stdout.write(self.style.SUCCESS("nada em folha DEFAULT — nada a migrar"))
            return

        total_rows = 0
        for r in results:
            total_rows += r.row_count
            scope = f"tenant={r.schema_name}" if r.schema_name else "todos os tenants deste mes"
            if execute:
                self.stdout.write(
                    f"movido {r.row_count} linha(s) de {r.source_leaf} "
                    f"(mes {r.month.year}-{r.month.month:02d}, {scope}) em {r.elapsed_s:.3f}s"
                )
            else:
                self.stdout.write(
                    f"[dry-run] moveria {r.row_count} linha(s) de {r.source_leaf} "
                    f"(mes {r.month.year}-{r.month.month:02d}, {scope})"
                )

        # "movimentação(ões)", não "linha(s) distinta(s)": uma linha que
        # nasceu na DEFAULT de topo E precisa de folha dedicada é contada em
        # DOIS grupos (a saída da DEFAULT de topo, depois a saída da DEFAULT
        # do mes) — cada grupo é uma DELETE+INSERT real medida à parte; somar
        # os dois não infla nada, só descreve com precisão o trabalho feito.
        verb = "movimentadas" if execute else "a movimentar"
        self.stdout.write(
            self.style.SUCCESS(
                f"total: {total_rows} movimentação(ões) de linha {verb} em {len(results)} grupo(s)"
            )
        )
        if not execute:
            self.stdout.write(
                self.style.WARNING("dry-run: nada foi tocado. Use --execute para aplicar.")
            )
