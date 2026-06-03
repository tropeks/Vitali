"""Management command: grade_stockout_predictions — stockout-prediction wedge S4.

Usage:
    python manage.py grade_stockout_predictions [--schema <schema_name>]

The nightly FLYWHEEL job. Grades every PAST-DUE ``stockout_risk`` prediction by
what ACTUALLY happened, so the model's accuracy can be tracked and improved over
time. Mirrors ``evaluate_stockout``'s structure (optional ``--schema`` +
``tenant_context``, thin command → ``StockoutService``); the manual trigger here
is the same surface, the automatic nightly schedule is registered via
``apps.pharmacy.tasks.grade_stockout_predictions`` (pharmacy migration 0012).

LABELING (LOCKED — docs/plans/STOCKOUT-WEDGE.md, "Flywheel (job noturno)"):
for each ``StockAlert`` with ``kind=stockout_risk``, ``outcome=pending`` and
``predicted_date <= today`` (past due):

  * **true_positive**  — current on-hand balance <= 0: it actually stocked out.
    Checked FIRST: a product that received a PO but STILL hit zero is a true
    stockout (the receipt wasn't enough), so zero-stock wins over intercepted.
  * **intercepted**    — else, IF a ``purchase_order_receiving`` movement landed
    for that product in ``(created_at, predicted_date]``: a replenishment
    arrived in time so the stockout was AVERTED — the system WORKING, explicitly
    NOT a false positive.
  * **false_positive** — else (balance > 0 and no receipt in the window):
    consumption slowed and the prediction missed.

IDEMPOTENT: only pending past-due ``stockout_risk`` alerts are candidates, so a
re-run grades nothing already graded and never regrades. ``expiry_waste`` alerts
are NEVER graded by this job. FLAG-INDEPENDENT: only grades already-created
alerts (it never creates one), so it runs regardless of the ``stockout_safety``
feature flag — if the flag is/was off there are simply no pending alerts and the
job is a no-op. The grading logic, N+1 avoidance and the per-grading AuditLog all
live in ``StockoutService.grade_predictions``.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone
from django_tenants.utils import get_tenant_model, tenant_context

from apps.pharmacy.models import StockAlert
from apps.pharmacy.services.stockout_safety import StockoutService


class Command(BaseCommand):
    help = (
        "Grade past-due stockout_risk predictions (flywheel) for the current "
        "(or given) tenant — idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            type=str,
            default=None,
            help="Tenant schema name. If omitted, uses the currently active tenant.",
        )

    def handle(self, *args, **options):
        schema = options["schema"]

        def _grade() -> dict[str, int]:
            return StockoutService().grade_predictions(now=timezone.now())

        if schema:
            TenantModel = get_tenant_model()
            try:
                tenant = TenantModel.objects.get(schema_name=schema)
            except TenantModel.DoesNotExist as exc:
                raise CommandError(f"Tenant com schema_name='{schema}' não encontrado.") from exc
            self.stdout.write(f"Gradando predições de ruptura no schema: {schema}")
            with tenant_context(tenant):
                counts = _grade()
        else:
            tenant = getattr(connection, "tenant", None)
            if tenant is None:
                raise CommandError("Nenhum tenant ativo. Informe --schema <schema_name>.")
            self.stdout.write(
                f"Gradando predições de ruptura no tenant ativo: {tenant.schema_name}"
            )
            counts = _grade()

        self._print_summary(counts)

    def _print_summary(self, counts: dict[str, int]) -> None:
        total = sum(counts.values())
        if total == 0:
            self.stdout.write(
                self.style.WARNING("Nenhuma predição vencida pendente para gradar (no-op).")
            )
            return
        tp = counts[StockAlert.Outcome.TRUE_POSITIVE]
        ic = counts[StockAlert.Outcome.INTERCEPTED]
        fp = counts[StockAlert.Outcome.FALSE_POSITIVE]
        self.stdout.write(
            self.style.SUCCESS(
                f"Flywheel: {total} predição(ões) gradada(s) — "
                f"acerto={tp}, interceptado={ic}, falso-positivo={fp}."
            )
        )
