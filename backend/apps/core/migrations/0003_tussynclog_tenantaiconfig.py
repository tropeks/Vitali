"""
Migration: TUSSSyncLog + TenantAIConfig (S-032 + S-033)
Both models live in the PUBLIC schema (SHARED_APPS).
Includes a RunPython backfill step to create TenantAIConfig rows for existing tenants.
"""

import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def backfill_tenant_ai_config(apps, schema_editor):
    """Create TenantAIConfig rows for all existing tenants that don't have one."""
    Tenant = apps.get_model("core", "Tenant")
    TenantAIConfig = apps.get_model("core", "TenantAIConfig")
    for tenant in Tenant.objects.all():
        TenantAIConfig.objects.get_or_create(tenant=tenant)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_add_tusscode"),
    ]

    operations = [
        migrations.CreateModel(
            name="TUSSSyncLog",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
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
                        max_length=30,
                    ),
                ),
                ("row_count_total", models.PositiveIntegerField(default=0)),
                ("row_count_added", models.PositiveIntegerField(default=0)),
                ("row_count_updated", models.PositiveIntegerField(default=0)),
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
                (
                    "error_message",
                    models.TextField(
                        blank=True,
                        help_text="Scrubbed: connection strings stripped, max 200 chars",
                    ),
                ),
                ("duration_ms", models.PositiveIntegerField(default=0)),
            ],
            options={
                "verbose_name": "TUSS Sync Log",
                "verbose_name_plural": "TUSS Sync Logs",
                "ordering": ["-ran_at"],
                "app_label": "core",
            },
        ),
        migrations.CreateModel(
            name="TenantAIConfig",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_config",
                        to="core.tenant",
                    ),
                ),
                (
                    "ai_tuss_enabled",
                    models.BooleanField(
                        default=False,
                        verbose_name="AI TUSS Auto-Coding ativado",
                        help_text="Habilita sugestão automática de códigos TUSS via IA para este tenant.",
                    ),
                ),
                (
                    "ai_glosa_prediction_enabled",
                    models.BooleanField(
                        default=False,
                        verbose_name="AI Glosa Prediction ativado",
                        help_text="Habilita predição de risco de glosa por item de guia para este tenant.",
                    ),
                ),
                (
                    "rate_limit_per_hour",
                    models.PositiveIntegerField(
                        default=500,
                        verbose_name="Limite de chamadas/hora",
                        help_text=(
                            "Default 500/hr covers 10-item guide creation with edits and insurer changes. "
                            "Reduce per-tenant if cost control is needed."
                        ),
                        validators=[
                            django.core.validators.MinValueValidator(10),
                            django.core.validators.MaxValueValidator(2000),
                        ],
                    ),
                ),
                (
                    "monthly_token_ceiling",
                    models.PositiveIntegerField(
                        default=500000,
                        verbose_name="Teto mensal de tokens",
                        help_text="Claude tokens/mês. A IA degrada silenciosamente quando excedido.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Configuração de IA por Tenant",
                "verbose_name_plural": "Configurações de IA por Tenant",
                "app_label": "core",
            },
        ),
        # Backfill existing tenants — safe for public-schema shared model
        migrations.RunPython(backfill_tenant_ai_config, reverse_code=noop),
    ]
