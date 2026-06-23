"""Issue #123 — WedgeValueSnapshot: daily per-tenant wedge ROI snapshots.

Lives in the public/shared schema (apps.core) so the platform operator reads
ROI per wedge per tenant from a single query, without per-request schema fan-out.
Rows are written daily by the ``core.snapshot_wedge_value`` Celery Beat task.
"""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0019_auditlog_immutable"),
    ]

    operations = [
        migrations.CreateModel(
            name="WedgeValueSnapshot",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "schema_name",
                    models.CharField(db_index=True, max_length=63, verbose_name="Schema do tenant"),
                ),
                (
                    "tenant_name",
                    models.CharField(blank=True, max_length=255, verbose_name="Nome do tenant"),
                ),
                (
                    "snapshot_date",
                    models.DateField(db_index=True, verbose_name="Data do snapshot"),
                ),
                (
                    "window_days",
                    models.PositiveIntegerField(
                        default=30,
                        help_text="Janela móvel usada no cálculo das métricas (ex.: últimos 30 dias).",
                        verbose_name="Janela (dias)",
                    ),
                ),
                (
                    "metrics",
                    models.JSONField(
                        default=dict,
                        help_text="Payload por wedge (glosa_safety, dose_safety, …) + agregados.",
                        verbose_name="Métricas por wedge",
                    ),
                ),
                (
                    "generated_at",
                    models.DateTimeField(auto_now=True, verbose_name="Gerado em"),
                ),
            ],
            options={
                "verbose_name": "Snapshot de Valor de Wedge",
                "verbose_name_plural": "Snapshots de Valor de Wedge",
                "ordering": ["-snapshot_date", "tenant_name"],
            },
        ),
        migrations.AddIndex(
            model_name="wedgevaluesnapshot",
            index=models.Index(
                fields=["snapshot_date", "schema_name"],
                name="core_wedgev_snapsho_0f525b_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="wedgevaluesnapshot",
            constraint=models.UniqueConstraint(
                fields=["schema_name", "snapshot_date"],
                name="uniq_wedge_value_snapshot_per_day",
            ),
        ),
    ]
