import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("hr", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkSchedule",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("weekly_hours", models.DecimalField(decimal_places=2, max_digits=5)),
                ("timezone", models.CharField(default="America/Sao_Paulo", max_length=64)),
                ("effective_from", models.DateField()),
                ("effective_until", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="work_schedules",
                        to="hr.employee",
                    ),
                ),
            ],
            options={"ordering": ["-effective_from"]},
        ),
        migrations.CreateModel(
            name="TimeEntry",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "event_type",
                    models.CharField(choices=[("in", "Entrada"), ("out", "Saída")], max_length=8),
                ),
                ("occurred_at", models.DateTimeField(db_index=True)),
                (
                    "source",
                    models.CharField(
                        choices=[("web", "Web"), ("mobile", "Mobile"), ("device", "Relógio")],
                        default="web",
                        max_length=16,
                    ),
                ),
                ("external_id", models.CharField(blank=True, default="", max_length=128)),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "correction_of",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="corrections",
                        to="hr.timeentry",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="time_entries",
                        to="hr.employee",
                    ),
                ),
                (
                    "recorded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recorded_time_entries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-occurred_at"]},
        ),
        migrations.CreateModel(
            name="OccupationalHealthExam",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "exam_type",
                    models.CharField(
                        choices=[
                            ("admission", "Admissional"),
                            ("periodic", "Periódico"),
                            ("return", "Retorno ao trabalho"),
                            ("role_change", "Mudança de risco"),
                            ("termination", "Demissional"),
                        ],
                        max_length=24,
                    ),
                ),
                ("performed_on", models.DateField()),
                ("expires_on", models.DateField(blank=True, db_index=True, null=True)),
                (
                    "result",
                    models.CharField(
                        choices=[("fit", "Apto"), ("unfit", "Inapto"), ("pending", "Pendente")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("provider_name", models.CharField(max_length=255)),
                ("certificate_reference", models.CharField(blank=True, max_length=128)),
                ("restrictions", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="health_exams",
                        to="hr.employee",
                    ),
                ),
                (
                    "recorded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recorded_health_exams",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-performed_on"]},
        ),
        migrations.AddConstraint(
            model_name="workschedule",
            constraint=models.CheckConstraint(
                condition=models.Q(("weekly_hours__gt", 0)), name="hr_schedule_positive_hours"
            ),
        ),
        migrations.AddConstraint(
            model_name="workschedule",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("effective_until__isnull", True),
                    ("effective_until__gte", models.F("effective_from")),
                    _connector="OR",
                ),
                name="hr_schedule_valid_period",
            ),
        ),
        migrations.AddConstraint(
            model_name="timeentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(("external_id", ""), _negated=True),
                fields=("source", "external_id"),
                name="hr_timeentry_source_external_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="occupationalhealthexam",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("expires_on__isnull", True),
                    ("expires_on__gte", models.F("performed_on")),
                    _connector="OR",
                ),
                name="hr_aso_valid_expiry",
            ),
        ),
    ]
