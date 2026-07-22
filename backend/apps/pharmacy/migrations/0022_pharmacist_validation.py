import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0032_clinical_operations"),
        ("pharmacy", "0021_enterprise_stock"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="PharmacistValidation",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendente"),
                            ("approved", "Aprovada"),
                            ("changes_requested", "Ajuste solicitado"),
                            ("rejected", "Rejeitada"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("clinical_notes", models.TextField(blank=True)),
                ("validated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "pharmacist",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pharmacist_validations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "prescription",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pharmacist_validation",
                        to="emr.prescription",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        )
    ]
