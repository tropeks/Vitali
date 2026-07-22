import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

import apps.core.fields


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0031_duplicatepatientcandidate_patientidentifier"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="MedicationAdministration",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("scheduled_at", models.DateTimeField(db_index=True)),
                ("administered_at", models.DateTimeField(db_index=True, default=timezone.now)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("given", "Administrado"),
                            ("omitted", "Omitido"),
                            ("refused", "Recusado"),
                            ("held", "Suspenso"),
                        ],
                        db_index=True,
                        max_length=10,
                    ),
                ),
                (
                    "dose_amount",
                    models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True),
                ),
                (
                    "dose_unit",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("mg", "mg"),
                            ("mcg", "mcg"),
                            ("mEq", "mEq"),
                            ("unit", "unit"),
                            ("g", "g"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "route",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("IV", "Intravenosa"),
                            ("IM", "Intramuscular"),
                            ("SC", "Subcutânea"),
                            ("PO", "Oral"),
                        ],
                        max_length=4,
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "administered_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="medication_administrations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "encounter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="medication_administrations",
                        to="emr.encounter",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="medication_administrations",
                        to="emr.patient",
                    ),
                ),
                (
                    "prescription_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="administrations",
                        to="emr.prescriptionitem",
                    ),
                ),
                (
                    "witness",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="witnessed_medication_administrations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-administered_at"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("prescription_item", "scheduled_at"),
                        name="emr_emar_one_event_per_scheduled_dose",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="NursingAssessment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("admission", "Admissão"),
                            ("diagnosis", "Diagnóstico de enfermagem"),
                            ("care_plan", "Planejamento"),
                            ("evolution", "Evolução"),
                            ("discharge", "Alta"),
                        ],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("content", apps.core.fields.EncryptedJSONField(default=dict)),
                ("signed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "authored_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="nursing_assessments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "encounter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="nursing_assessments",
                        to="emr.encounter",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="nursing_assessments",
                        to="emr.patient",
                    ),
                ),
                (
                    "signed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="signed_nursing_assessments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
