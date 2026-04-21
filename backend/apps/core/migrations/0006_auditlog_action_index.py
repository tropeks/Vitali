"""
S-058: Composite index on AuditLog(action, created_at).

Speeds up security monitoring queries like:
  AuditLog.objects.filter(action='login', created_at__gte=last_week)
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_asaas_charge_map"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["action", "created_at"],
                name="core_auditlog_act_created_idx",
            ),
        ),
    ]
