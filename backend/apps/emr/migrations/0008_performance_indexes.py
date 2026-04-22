"""
S-058: Performance indexes — Sprint 14 pilot readiness.

1. Function index on Appointment.start_time for DATE() queries
   (QuerySet.filter(start_time__date=today) extracts DATE, which needs
   a matching expression index — the existing btree on start_time alone
   is not used by the planner for date extraction).

2. GIN index on Patient.insurance_data JSONB column
   (clinic queries filter on insurance_data->>'operator' etc.)
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0007_appointment_satisfaction_rating"),
    ]

    operations = [
        # RunSQL is required here because Django ORM cannot express a function
        # index (DATE(start_time AT TIME ZONE ...)) via models.Index.
        migrations.RunSQL(
            sql="""
            CREATE INDEX IF NOT EXISTS
                emr_appointment_start_date_saopaulo_idx
            ON emr_appointment
            (DATE(start_time AT TIME ZONE 'America/Sao_Paulo'));
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS emr_appointment_start_date_saopaulo_idx;
            """,
            state_operations=[],  # No model state change — pure DB index
        ),
        migrations.RunSQL(
            sql="""
            CREATE INDEX IF NOT EXISTS
                emr_patient_insurance_data_gin_idx
            ON emr_patient
            USING gin (insurance_data jsonb_path_ops);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS emr_patient_insurance_data_gin_idx;
            """,
            state_operations=[],
        ),
    ]
