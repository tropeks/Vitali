# Generated manually for the governance foundation.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="ApprovalRequest",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("workflow_key", models.CharField(db_index=True, max_length=100)),
                ("reference_type", models.CharField(max_length=100)),
                ("reference_id", models.CharField(max_length=100)),
                ("title", models.CharField(max_length=255)),
                ("context", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendente"),
                            ("approved", "Aprovada"),
                            ("rejected", "Rejeitada"),
                            ("cancelled", "Cancelada"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="DomainEventOutbox",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("idempotency_key", models.CharField(max_length=255, unique=True)),
                ("aggregate_type", models.CharField(max_length=100)),
                ("aggregate_id", models.CharField(max_length=100)),
                ("event_type", models.CharField(db_index=True, max_length=150)),
                ("payload", models.JSONField()),
                ("occurred_at", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendente"),
                            ("processing", "Processando"),
                            ("published", "Publicado"),
                            ("failed", "Falhou"),
                            ("dead", "Esgotado"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("available_at", models.DateTimeField()),
                ("last_error", models.TextField(blank=True)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ("created_at",)},
        ),
        migrations.CreateModel(
            name="ApprovalStep",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("sequence", models.PositiveSmallIntegerField()),
                ("permission_required", models.CharField(max_length=100)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendente"),
                            ("approved", "Aprovada"),
                            ("rejected", "Rejeitada"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("decision_note", models.TextField(blank=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approval",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="steps",
                        to="governance.approvalrequest",
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval_steps_decided",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("sequence",)},
        ),
        migrations.AddIndex(
            model_name="approvalrequest",
            index=models.Index(fields=["status", "created_at"], name="gov_approval_status_created"),
        ),
        migrations.AddIndex(
            model_name="approvalrequest",
            index=models.Index(
                fields=["reference_type", "reference_id"], name="gov_approval_reference"
            ),
        ),
        migrations.AddIndex(
            model_name="domaineventoutbox",
            index=models.Index(fields=["status", "available_at"], name="gov_outbox_dispatch"),
        ),
        migrations.AddIndex(
            model_name="domaineventoutbox",
            index=models.Index(
                fields=["aggregate_type", "aggregate_id"], name="gov_outbox_aggregate"
            ),
        ),
        migrations.AddConstraint(
            model_name="approvalstep",
            constraint=models.UniqueConstraint(
                fields=("approval", "sequence"), name="gov_unique_approval_sequence"
            ),
        ),
    ]
