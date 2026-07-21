import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0028_expand_laboratory_domain"),
        ("signatures", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LabReportArtifact",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("pdf", models.BinaryField()),
                ("released_at", models.DateTimeField(auto_now_add=True)),
                (
                    "order",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="report_artifact",
                        to="emr.laborder",
                    ),
                ),
                (
                    "released_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="released_lab_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "signature",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lab_report_artifact",
                        to="signatures.digitalsignature",
                    ),
                ),
            ],
            options={"ordering": ["-released_at"]},
        ),
    ]
