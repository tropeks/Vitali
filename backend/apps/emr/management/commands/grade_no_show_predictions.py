"""Management command: grade_no_show_predictions — no-show wedge N2 flywheel.

Usage:
    python manage.py grade_no_show_predictions [--schema <schema_name>]

Grades every past-due ``NoShowRisk`` whose appointment reached a terminal status
(``completed``/``no_show``) by what actually happened: medium+high bands =
predicted-positive, low = predicted-negative → 4-way outcome. ``cancelled``
appointments are excluded entirely. IDEMPOTENT (only ``outcome=pending`` rows are
candidates) and FLAG-INDEPENDENT (only grades existing rows, never creates).
Thin command → ``NoShowService.grade_predictions``.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone
from django_tenants.utils import get_tenant_model, tenant_context

from apps.emr.services.no_show import NoShowService


class Command(BaseCommand):
    help = "Grade past-due no-show predictions (flywheel) for the current or given tenant."

    def add_arguments(self, parser):
        parser.add_argument("--schema", type=str, default=None)

    def handle(self, *args, **options):
        schema = options["schema"]

        def _run() -> dict[str, int]:
            return NoShowService().grade_predictions(now=timezone.now())

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

        total = sum(counts.values())
        if total == 0:
            self.stdout.write(self.style.WARNING("Nenhuma predição vencida pendente (no-op)."))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Flywheel no-show: {total} gradada(s) — "
                f"TP={counts['true_positive']}, FP={counts['false_positive']}, "
                f"FN={counts['false_negative']}, TN={counts['true_negative']}."
            )
        )
