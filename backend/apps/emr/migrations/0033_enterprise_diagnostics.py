import uuid

import django.db.models.deletion
import django.utils.timezone
import encrypted_model_fields.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0022_wedgevaluesnapshot"), ("emr", "0032_clinical_operations")]

    operations = [
        migrations.CreateModel(
            name="LabInstrument",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("code", models.CharField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=120)),
                (
                    "protocol",
                    models.CharField(
                        choices=[
                            ("hl7_v2", "HL7 v2"),
                            ("astm", "ASTM"),
                            ("canonical", "JSON canônico"),
                        ],
                        max_length=16,
                    ),
                ),
                ("endpoint", models.CharField(blank=True, max_length=255)),
                ("supports_orders", models.BooleanField(default=True)),
                ("supports_results", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="LabSpecimen",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("barcode", models.CharField(db_index=True, max_length=80, unique=True)),
                ("specimen_type", models.CharField(max_length=80)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("expected", "Aguardando coleta"),
                            ("collected", "Coletado"),
                            ("received", "Recebido"),
                            ("processing", "Em processamento"),
                            ("stored", "Armazenado"),
                            ("disposed", "Descartado"),
                            ("rejected", "Rejeitado"),
                        ],
                        default="expected",
                        max_length=16,
                    ),
                ),
                ("current_location", models.CharField(blank=True, max_length=120)),
                ("collected_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "collected_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lab_specimens_collected",
                        to="core.user",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="specimens",
                        to="emr.laborder",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="CriticalLabResult",
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
                        choices=[("open", "Aberto"), ("acknowledged", "Reconhecido")],
                        db_index=True,
                        default="open",
                        max_length=16,
                    ),
                ),
                ("detected_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                (
                    "acknowledgement_note",
                    encrypted_model_fields.fields.EncryptedTextField(blank=True),
                ),
                (
                    "acknowledged_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="critical_results_acknowledged",
                        to="core.user",
                    ),
                ),
                (
                    "detected_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="critical_results_detected",
                        to="core.user",
                    ),
                ),
                (
                    "order_item",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="critical_result",
                        to="emr.laborderitem",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="LabSpecimenEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("event_type", models.CharField(max_length=32)),
                ("from_location", models.CharField(blank=True, max_length=120)),
                ("to_location", models.CharField(blank=True, max_length=120)),
                ("reason", models.CharField(blank=True, max_length=255)),
                (
                    "occurred_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "instrument",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="specimen_events",
                        to="emr.labinstrument",
                    ),
                ),
                (
                    "performed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lab_specimen_events",
                        to="core.user",
                    ),
                ),
                (
                    "specimen",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="events",
                        to="emr.labspecimen",
                    ),
                ),
            ],
            options={"ordering": ["occurred_at", "created_at"]},
        ),
    ]
