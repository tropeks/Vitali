"""E1-T1 — TerminologyImportLog: generic provenance log for terminology catalog
imports (CID-10 and future catalogs). Lives in the public/shared schema.
"""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_wedgevaluesnapshot"),
    ]

    operations = [
        migrations.CreateModel(
            name="TerminologyImportLog",
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
                    "system",
                    models.CharField(
                        db_index=True, max_length=32, verbose_name="Sistema/terminologia"
                    ),
                ),
                (
                    "version",
                    models.CharField(blank=True, default="", max_length=32, verbose_name="Versão"),
                ),
                ("ran_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("management_command", "Management Command"),
                            ("api", "API"),
                            ("scheduled", "Agendado"),
                        ],
                        default="management_command",
                        help_text="Origem da carga (ex.: DATASUS via management command).",
                        max_length=30,
                    ),
                ),
                (
                    "provenance",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Fonte de dados dos registros (ex.: DATASUS).",
                        max_length=100,
                        verbose_name="Proveniência",
                    ),
                ),
                ("row_count_total", models.PositiveIntegerField(default=0)),
                ("row_count_added", models.PositiveIntegerField(default=0)),
                ("row_count_updated", models.PositiveIntegerField(default=0)),
                ("row_count_errors", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("success", "Sucesso"),
                            ("partial", "Parcial"),
                            ("error", "Erro"),
                        ],
                        default="success",
                        max_length=10,
                    ),
                ),
                ("dry_run", models.BooleanField(default=False)),
                (
                    "error_message",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Amostra dos erros por linha (truncada).",
                    ),
                ),
                ("duration_ms", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Log de Importação de Terminologia",
                "verbose_name_plural": "Logs de Importação de Terminologia",
                "ordering": ["-ran_at"],
            },
        ),
    ]
