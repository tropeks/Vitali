"""Management command: evaluate_stockout — stockout-prediction wedge S3.

Usage:
    python manage.py evaluate_stockout [--schema <schema_name>]

Manually triggers the deterministic supply-risk evaluation for ONE tenant:
runs ``StockoutService.evaluate_all(now=timezone.now())`` over every CONFIGURED
catalog product (those with a ``lead_time_days``), persisting/refreshing
``StockAlert`` rows (stockout_risk + expiry_waste) for the proactive risk
dashboard (``StockRiskView``).

This is the MANUAL trigger. The nightly automatic schedule is wedge S4.

IDEMPOTENT: the service upserts via ``update_or_create`` on the StockAlert
unique constraint — re-running never duplicates an alert, never clobbers an
acknowledged override whose prediction is unchanged, and resolves alerts the
engine no longer predicts. Safe to run repeatedly.

ADVISE ONLY: this is the proactive supply surface. It NEVER blocks a dispense —
there is no DispenseView gate anywhere in this wedge. When the tenant's
``stockout_safety`` feature flag is OFF, the service is a no-op (no StockAlert is
written).
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone
from django_tenants.utils import get_tenant_model, tenant_context

from apps.pharmacy.services.stockout_safety import StockoutService


class Command(BaseCommand):
    help = "Evaluate stockout/expiry risk for the current (or given) tenant — idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            type=str,
            default=None,
            help="Tenant schema name. If omitted, uses the currently active tenant.",
        )

    def handle(self, *args, **options):
        schema = options["schema"]

        def _evaluate():
            # ``is_enabled`` reads connection.tenant; ``tenant_context`` (below) sets
            # both the search_path AND connection.tenant, so the flag resolves.
            if not StockoutService.is_enabled():
                self.stdout.write(
                    self.style.WARNING(
                        "stockout_safety está DESLIGADO neste tenant — nada a avaliar (no-op)."
                    )
                )
                return
            StockoutService().evaluate_all(now=timezone.now())
            self.stdout.write(
                self.style.SUCCESS("Avaliação de ruptura/validade concluída (upsert idempotente).")
            )

        if schema:
            TenantModel = get_tenant_model()
            try:
                tenant = TenantModel.objects.get(schema_name=schema)
            except TenantModel.DoesNotExist as exc:
                raise CommandError(f"Tenant com schema_name='{schema}' não encontrado.") from exc
            self.stdout.write(f"Avaliando estoque no schema: {schema}")
            with tenant_context(tenant):
                _evaluate()
        else:
            tenant = getattr(connection, "tenant", None)
            if tenant is None:
                raise CommandError("Nenhum tenant ativo. Informe --schema <schema_name>.")
            self.stdout.write(f"Avaliando estoque no tenant ativo: {tenant.schema_name}")
            _evaluate()
