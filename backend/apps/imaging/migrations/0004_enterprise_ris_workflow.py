import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_wedgevaluesnapshot"),
        ("emr", "0033_enterprise_diagnostics"),
        ("imaging", "0003_dicom_patient_identity"),
    ]
    operations = [
        migrations.CreateModel(
            name="ImagingModality",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("ae_title", models.CharField(max_length=16, unique=True)),
                ("name", models.CharField(max_length=120)),
                (
                    "modality",
                    models.CharField(
                        choices=[
                            ("CR", "Computed Radiography"),
                            ("CT", "Computed Tomography"),
                            ("DX", "Digital Radiography"),
                            ("MG", "Mammography"),
                            ("MR", "Magnetic Resonance"),
                            ("NM", "Nuclear Medicine"),
                            ("OT", "Other"),
                            ("PT", "Positron Emission Tomography (PET)"),
                            ("RF", "Radio Fluoroscopy"),
                            ("US", "Ultrasound"),
                            ("XA", "X-Ray Angiography"),
                        ],
                        max_length=4,
                    ),
                ),
                ("host", models.CharField(max_length=255)),
                ("port", models.PositiveIntegerField(default=104)),
                ("supports_mwl", models.BooleanField(default=True)),
                ("supports_mpps", models.BooleanField(default=True)),
                ("supports_storage_commitment", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("last_echo_at", models.DateTimeField(blank=True, null=True)),
                ("last_echo_ok", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="ModalityWorklistItem",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("accession_number", models.CharField(db_index=True, max_length=64, unique=True)),
                ("requested_procedure_id", models.CharField(max_length=64)),
                ("requested_procedure_description", models.CharField(max_length=255)),
                ("scheduled_at", models.DateTimeField(db_index=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("scheduled", "Agendado"),
                            ("in_progress", "Em execução"),
                            ("completed", "Concluído"),
                            ("discontinued", "Descontinuado"),
                        ],
                        default="scheduled",
                        max_length=16,
                    ),
                ),
                ("study_instance_uid", models.CharField(blank=True, db_index=True, max_length=128)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="imaging_worklist_created",
                        to="core.user",
                    ),
                ),
                (
                    "encounter",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="emr.encounter",
                    ),
                ),
                (
                    "modality",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="worklist",
                        to="imaging.imagingmodality",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="imaging_worklist",
                        to="emr.patient",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DicomWorkflowEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("event_uid", models.CharField(max_length=128)),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("mpps_in_progress", "MPPS em execução"),
                            ("mpps_completed", "MPPS concluído"),
                            ("mpps_discontinued", "MPPS descontinuado"),
                            ("storage_commitment", "Storage Commitment"),
                        ],
                        max_length=24,
                    ),
                ),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("success", models.BooleanField(default=True)),
                ("error", models.CharField(blank=True, max_length=255)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                (
                    "modality",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workflow_events",
                        to="imaging.imagingmodality",
                    ),
                ),
                (
                    "worklist_item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="events",
                        to="imaging.modalityworklistitem",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="dicomworkflowevent",
            constraint=models.UniqueConstraint(
                fields=("modality", "event_uid"), name="img_workflow_event_unique"
            ),
        ),
    ]
