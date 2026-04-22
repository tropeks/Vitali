"""
S-069: AIScribeSession — AI Clinical Scribe
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0005_rename_ai_glosa_tuss_insurer_idx_ai_glosapre_tuss_co_a35a65_idx_and_more"),
        ("emr", "0012_waitlistentry"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIScribeSession",
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
                    "encounter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scribe_sessions",
                        to="emr.encounter",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("processing", "Processing"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="processing",
                        max_length=20,
                    ),
                ),
                ("raw_transcription", models.TextField()),
                (
                    "soap_json",
                    models.JSONField(
                        blank=True,
                        help_text="Generated SOAP fields: {subjective, objective, assessment, plan}",
                        null=True,
                    ),
                ),
                ("error_message", models.TextField(blank=True)),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="aiscribesession",
            index=models.Index(
                fields=["encounter", "status"],
                name="ai_scribe_encounter_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="aiscribesession",
            index=models.Index(
                fields=["encounter", "-created_at"],
                name="ai_scribe_encounter_created_idx",
            ),
        ),
    ]
