# Generated for the Wave 0 protocol-neutral integration backbone.

import uuid

from django.db import migrations, models

import apps.core.fields


class Migration(migrations.Migration):
    dependencies = [("governance", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="domaineventoutbox",
            name="replay_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="IntegrationInbox",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("idempotency_key", models.CharField(max_length=255, unique=True)),
                ("source", models.CharField(db_index=True, max_length=100)),
                ("message_type", models.CharField(db_index=True, max_length=150)),
                ("correlation_id", models.CharField(blank=True, db_index=True, max_length=255)),
                ("payload", apps.core.fields.EncryptedJSONField()),
                ("headers", apps.core.fields.EncryptedJSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("received", "Recebida"),
                            ("processing", "Processando"),
                            ("completed", "Concluída"),
                            ("failed", "Falhou"),
                            ("dead", "Esgotada"),
                        ],
                        default="received",
                        max_length=20,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("replay_count", models.PositiveIntegerField(default=0)),
                ("available_at", models.DateTimeField()),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("-received_at",)},
        ),
        migrations.AddIndex(
            model_name="integrationinbox",
            index=models.Index(fields=["status", "available_at"], name="gov_inbox_dispatch"),
        ),
        migrations.AddIndex(
            model_name="integrationinbox",
            index=models.Index(fields=["source", "message_type"], name="gov_inbox_source_type"),
        ),
    ]
