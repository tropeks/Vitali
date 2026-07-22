import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("patient_portal", "0001_initial"),
        ("emr", "0015_encounter_signed_at_signed_by"),
    ]
    operations = [
        migrations.CreateModel(
            name="PatientRepresentative",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "relationship",
                    models.CharField(
                        choices=[
                            ("guardian", "Responsável"),
                            ("parent", "Parente"),
                            ("caregiver", "Cuidador"),
                            ("other", "Outro"),
                        ],
                        default="guardian",
                        max_length=20,
                    ),
                ),
                ("active", models.BooleanField(default=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="portal_representatives",
                        to="emr.patient",
                    ),
                ),
                (
                    "representative",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="portal_patient_relationships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PortalConsent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("purpose", models.CharField(max_length=80)),
                ("policy_version", models.CharField(max_length=30)),
                ("granted_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "granted_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="portal_consents_granted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="portal_consents",
                        to="emr.patient",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="patientrepresentative",
            constraint=models.UniqueConstraint(
                fields=("patient", "representative"), name="portal_rep_unique"
            ),
        ),
        migrations.AddIndex(
            model_name="portalconsent",
            index=models.Index(
                fields=["patient", "purpose"], name="portal_consent_patient_idx"
            ),
        ),
    ]
