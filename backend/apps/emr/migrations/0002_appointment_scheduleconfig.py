import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0001_initial"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScheduleConfig",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("slot_duration_minutes", models.IntegerField(default=30)),
                ("working_days", models.JSONField(default=list)),
                ("working_hours_start", models.TimeField(default="08:00")),
                ("working_hours_end", models.TimeField(default="18:00")),
                ("lunch_start", models.TimeField(blank=True, null=True)),
                ("lunch_end", models.TimeField(blank=True, null=True)),
                ("max_simultaneous", models.IntegerField(default=1)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "professional",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="schedule_config",
                        to="emr.professional",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Appointment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("start_time", models.DateTimeField(db_index=True)),
                ("end_time", models.DateTimeField()),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("consultation", "Consulta"),
                            ("return", "Retorno"),
                            ("exam", "Exame"),
                            ("procedure", "Procedimento"),
                            ("telemedicine", "Telemedicina"),
                        ],
                        default="consultation",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("scheduled", "Agendado"),
                            ("confirmed", "Confirmado"),
                            ("waiting", "Aguardando"),
                            ("in_progress", "Em atendimento"),
                            ("completed", "Concluído"),
                            ("cancelled", "Cancelado"),
                            ("no_show", "Não compareceu"),
                        ],
                        default="scheduled",
                        max_length=20,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("receptionist", "Recepcionista"),
                            ("whatsapp", "WhatsApp"),
                            ("web", "Portal Web"),
                            ("phone", "Telefone"),
                        ],
                        default="receptionist",
                        max_length=20,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("whatsapp_reminder_sent", models.BooleanField(default=False)),
                ("whatsapp_confirmed", models.BooleanField(default=False)),
                ("cancellation_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="appointments",
                        to="emr.patient",
                    ),
                ),
                (
                    "professional",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="appointments",
                        to="emr.professional",
                    ),
                ),
                (
                    "cancelled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cancelled_appointments",
                        to="core.user",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_appointments",
                        to="core.user",
                    ),
                ),
            ],
            options={
                "ordering": ["start_time"],
            },
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(
                fields=["professional", "start_time"], name="emr_appoint_profess_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["patient", "start_time"], name="emr_appoint_patient_idx"),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["status", "start_time"], name="emr_appoint_status_idx"),
        ),
        migrations.AddIndex(
            model_name="appointment",
            index=models.Index(fields=["start_time", "end_time"], name="emr_appoint_start_end_idx"),
        ),
    ]
