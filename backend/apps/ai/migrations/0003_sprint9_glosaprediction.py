"""
Migration: GlosaPrediction model (S-034 — Glosa Prediction)
Lives in the TENANT schema (apps.ai is a TENANT_APP).
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0002_aiprompttemplate_versioning"),
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="GlosaPrediction",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("guide", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="glosa_predictions",
                    to="billing.tissguide",
                )),
                ("tuss_code", models.CharField(db_index=True, max_length=20)),
                ("insurer_ans_code", models.CharField(max_length=20)),
                ("cid10_codes", models.JSONField(default=list)),
                ("guide_type", models.CharField(max_length=20)),
                ("risk_level", models.CharField(
                    choices=[("low", "Baixo"), ("medium", "Médio"), ("high", "Alto")],
                    db_index=True,
                    max_length=10,
                )),
                ("risk_reason", models.TextField()),
                ("risk_code", models.CharField(
                    blank=True,
                    help_text="GLOSA_REASON_CODE best match, if applicable",
                    max_length=5,
                )),
                ("usage_log", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="glosa_predictions",
                    to="ai.aiusagelog",
                )),
                ("was_denied", models.BooleanField(
                    blank=True,
                    help_text="Backfilled by retorno parser when denial confirmed (guide-level)",
                    null=True,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["tuss_code", "insurer_ans_code"], name="ai_glosa_tuss_insurer_idx"),
                    models.Index(fields=["guide", "was_denied"], name="ai_glosa_guide_denied_idx"),
                    models.Index(fields=["created_at"], name="ai_glosa_created_at_idx"),
                ],
            },
        ),
    ]
