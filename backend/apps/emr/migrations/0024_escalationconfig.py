import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0023_no_show_beat_schedule"),
    ]

    operations = [
        migrations.CreateModel(
            name="EscalationConfig",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                (
                    "notify_emails",
                    models.JSONField(
                        default=list,
                        help_text="Lista de e-mails notificados em escalamentos (formato JSON).",
                    ),
                ),
                (
                    "notify_role",
                    models.CharField(
                        blank=True,
                        help_text=(
                            "Chave de papel opcional (ex: 'nurse_coordinator') resolvida em runtime."
                        ),
                        max_length=50,
                    ),
                ),
                (
                    "min_severity",
                    models.CharField(
                        choices=[("advise", "Avisa"), ("escalation", "Escalonamento (emergência)")],
                        default="escalation",
                        help_text="Severidade mínima para acionar o roteamento.",
                        max_length=12,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Configuração de escalonamento",
                "verbose_name_plural": "Configurações de escalonamento",
            },
        ),
    ]
