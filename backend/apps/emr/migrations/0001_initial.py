import uuid

import django.db.models.deletion
import encrypted_model_fields.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Patient",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ("medical_record_number", models.CharField(blank=True, max_length=20, unique=True)),
                ("full_name", models.CharField(db_index=True, max_length=200)),
                ("social_name", models.CharField(blank=True, max_length=200)),
                ("cpf", encrypted_model_fields.fields.EncryptedCharField(max_length=14)),
                ("birth_date", models.DateField()),
                (
                    "gender",
                    models.CharField(
                        choices=[
                            ("M", "Masculino"),
                            ("F", "Feminino"),
                            ("O", "Outro"),
                            ("N", "Não informado"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "blood_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("A+", "A+"),
                            ("A-", "A-"),
                            ("B+", "B+"),
                            ("B-", "B-"),
                            ("AB+", "AB+"),
                            ("AB-", "AB-"),
                            ("O+", "O+"),
                            ("O-", "O-"),
                        ],
                        max_length=5,
                    ),
                ),
                ("phone", models.CharField(blank=True, max_length=20)),
                ("whatsapp", models.CharField(blank=True, db_index=True, max_length=20)),
                ("email", models.EmailField(blank=True)),
                ("address", models.JSONField(blank=True, default=dict)),
                ("insurance_data", models.JSONField(blank=True, default=dict)),
                ("emergency_contact", models.JSONField(blank=True, default=dict)),
                ("photo_url", models.URLField(blank=True)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="patients_created",
                        to="core.user",
                    ),
                ),
            ],
            options={"ordering": ["full_name"]},
        ),
        migrations.CreateModel(
            name="Allergy",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ("substance", models.CharField(max_length=200)),
                ("reaction", models.CharField(blank=True, max_length=500)),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("mild", "Leve"),
                            ("moderate", "Moderada"),
                            ("severe", "Grave"),
                            ("life_threatening", "Risco de vida"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Ativa"),
                            ("inactive", "Inativa"),
                            ("resolved", "Resolvida"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allergies",
                        to="emr.patient",
                    ),
                ),
                (
                    "confirmed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="core.user",
                    ),
                ),
            ],
            options={"ordering": ["-severity", "substance"], "verbose_name_plural": "allergies"},
        ),
        migrations.CreateModel(
            name="MedicalHistory",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ("condition", models.CharField(max_length=300)),
                ("cid10_code", models.CharField(blank=True, max_length=10)),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("chronic", "Crônica"),
                            ("acute", "Aguda"),
                            ("surgical", "Cirúrgica"),
                            ("family", "Familiar"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Ativa"),
                            ("controlled", "Controlada"),
                            ("resolved", "Resolvida"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("onset_date", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="medical_history",
                        to="emr.patient",
                    ),
                ),
            ],
            options={"ordering": ["condition"], "verbose_name_plural": "medical histories"},
        ),
        migrations.CreateModel(
            name="Professional",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                (
                    "council_type",
                    models.CharField(
                        choices=[
                            ("CRM", "CRM"),
                            ("COREN", "COREN"),
                            ("CRF", "CRF"),
                            ("CRO", "CRO"),
                            ("CREFITO", "CREFITO"),
                            ("CRP", "CRP"),
                        ],
                        max_length=10,
                    ),
                ),
                ("council_number", models.CharField(max_length=20)),
                ("council_state", models.CharField(max_length=2)),
                ("specialty", models.CharField(blank=True, max_length=100)),
                ("cbo_code", models.CharField(blank=True, max_length=10)),
                ("cnes_code", models.CharField(blank=True, max_length=10)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="professional",
                        to="core.user",
                    ),
                ),
            ],
            options={"unique_together": {("council_type", "council_number", "council_state")}},
        ),
        migrations.AddIndex(
            model_name="patient",
            index=models.Index(fields=["full_name"], name="emr_patient_full_name_idx"),
        ),
        migrations.AddIndex(
            model_name="patient",
            index=models.Index(fields=["medical_record_number"], name="emr_patient_mrn_idx"),
        ),
        migrations.AddIndex(
            model_name="patient",
            index=models.Index(
                fields=["is_active", "full_name"], name="emr_patient_active_name_idx"
            ),
        ),
    ]
