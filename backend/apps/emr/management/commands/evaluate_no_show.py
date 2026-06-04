"""Management command: evaluate_no_show — no-show prediction wedge N2.

Usage:
    python manage.py evaluate_no_show [--schema <schema_name>] [--horizon-days N]

Proactive job: scores every upcoming appointment in the window and upserts a
``NoShowRisk`` row. No-op when the ``no_show_prediction`` flag is OFF. Thin
command → ``NoShowService.evaluate_window``; the automatic nightly schedule is
registered via ``apps.emr.tasks_no_show`` (emr migration). ADVISE only — never
blocks booking/check-in.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone
from django_tenants.utils import get_tenant_model, tenant_context

from apps.emr.services.no_show import DEFAULT_HORIZON_DAYS, NoShowService


class Command(BaseCommand):
    help = "Score upcoming appointments for no-show risk (current or given tenant)."

    def add_arguments(self, parser):
        parser.add_argument("--schema", type=str, default=None)
        parser.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS)

    def handle(self, *args, **options):
        schema = options["schema"]
        horizon = options["horizon_days"]

        def _run() -> dict[str, int]:
            return NoShowService().evaluate_window(now=timezone.now(), horizon_days=horizon)

        if schema:
            TenantModel = get_tenant_model()
            try:
                tenant = TenantModel.objects.get(schema_name=schema)
            except TenantModel.DoesNotExist as exc:
                raise CommandError(f"Tenant com schema_name='{schema}' não encontrado.") from exc
            with tenant_context(tenant):
                counts = _run()
        else:
            if getattr(connection, "tenant", None) is None:
                raise CommandError("Nenhum tenant ativo. Informe --schema <schema_name>.")
            counts = _run()

        self.stdout.write(
            self.style.SUCCESS(
                f"No-show: {counts['scored']} agendamento(s) pontuado(s), "
                f"{counts['inert']} inerte(s) (histórico insuficiente)."
            )
        )
