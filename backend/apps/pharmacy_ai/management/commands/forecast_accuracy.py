"""Management command: forecast_accuracy — AI Farmácia learned model (issue #131).

Usage:
    python manage.py forecast_accuracy [--schema <schema_name>] [--target-days N]
                                       [--limit N]

Back-tests the learned seasonal forecaster against the arithmetic baseline for
each drug with dispensation history in the tenant and prints a per-drug MAPE
comparison (learned vs baseline) plus an aggregate win-rate. Read-only — it
trains in-memory and persists nothing. Useful for verifying the acceptance
criterion (learned MAPE < baseline MAPE on hold-out) against real pilot data.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone
from django_tenants.utils import get_tenant_model, tenant_context

from apps.pharmacy.models import Drug
from apps.pharmacy_ai.services import learned
from apps.pharmacy_ai.services.forecast import HOLDOUT_DAYS, TRAIN_LOOKBACK_DAYS
from apps.pharmacy_ai.services.timeseries import build_daily_demand


class Command(BaseCommand):
    help = "Back-test the learned demand forecaster vs the arithmetic baseline (MAPE)."

    def add_arguments(self, parser):
        parser.add_argument("--schema", type=str, default=None)
        parser.add_argument("--limit", type=int, default=None, help="Max drugs to evaluate.")

    def handle(self, *args, **options):
        schema = options["schema"]
        limit = options["limit"]

        def _run() -> None:
            self._report(limit=limit)

        if schema:
            TenantModel = get_tenant_model()
            try:
                tenant = TenantModel.objects.get(schema_name=schema)
            except TenantModel.DoesNotExist as exc:
                raise CommandError(f"Tenant com schema_name='{schema}' não encontrado.") from exc
            with tenant_context(tenant):
                _run()
        else:
            if getattr(connection, "tenant", None) is None:
                raise CommandError("Nenhum tenant ativo. Informe --schema <schema_name>.")
            _run()

    def _report(self, *, limit: int | None) -> None:
        now = timezone.now()
        drugs = Drug.objects.all().order_by("generic_name", "name")
        if limit:
            drugs = drugs[:limit]

        evaluated = 0
        learned_wins = 0
        for drug in drugs:
            history = build_daily_demand(drug, end=now, days=TRAIN_LOOKBACK_DAYS)
            report = learned.evaluate_models(history, holdout_days=HOLDOUT_DAYS)
            if report is None or report.mape_learned is None or report.mape_baseline is None:
                continue
            evaluated += 1
            if report.improved:
                learned_wins += 1
            flag = "✓" if report.improved else " "
            name = getattr(drug, "generic_name", "") or getattr(drug, "name", "") or str(drug.pk)
            self.stdout.write(
                f"[{flag}] {name[:40]:<40} "
                f"learned={report.mape_learned:6.2f}%  baseline={report.mape_baseline:6.2f}%"
            )

        if evaluated == 0:
            self.stdout.write(
                self.style.WARNING("Nenhum medicamento com histórico suficiente para back-test.")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Modelo aprendido venceu em {learned_wins}/{evaluated} medicamentos "
                f"({100.0 * learned_wins / evaluated:.0f}%)."
            )
        )
