"""Data migration — registra a task diária de acúmulo de diárias (B5).

Cria uma PeriodicTask em django_celery_beat:
  * billing.accrue_active_admissions — diariamente às 02:00 UTC

Espelha apps/pharmacy/migrations/0012: o ``DatabaseScheduler`` ignora o dict
``CELERY_BEAT_SCHEDULE`` do settings a menos que a linha de PeriodicTask exista,
então a migração é que a cria de forma confiável (get_or_create → idempotente).

02:00 UTC (23:00 em Brasília) é depois da virada do dia e antes da janela de
backup das 03:00, e a task é idempotente — rodar de novo no mesmo dia não
duplica diária, por causa da UniqueConstraint (admission, service_date).
"""

from django.db import migrations


def register_periodic_task(apps, schema_editor):
    try:
        CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        # django_celery_beat não instalado — sai sem quebrar.
        return

    daily_cron, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="2",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
    )

    PeriodicTask.objects.get_or_create(
        name="billing.accrue_active_admissions",
        defaults={
            "task": "billing.accrue_active_admissions",
            "crontab": daily_cron,
            "enabled": True,
            "description": (
                "B5: acumula as diárias de leito das internações ativas em todos "
                "os tenants, diariamente às 02:00 UTC. Rede de segurança do hook "
                "de alta — sem ela, a receita de uma estada longa fica pendurada "
                "num único evento."
            ),
        },
    )


def unregister_periodic_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    except LookupError:
        return
    PeriodicTask.objects.filter(name="billing.accrue_active_admissions").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0030_apac_situacao_cid"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(register_periodic_task, unregister_periodic_task),
    ]
