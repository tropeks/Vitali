"""M2-S3-T2 — reconcile legacy LabTest.loinc_code onto the governed core.LoincCode FK.

Best-effort, data-preserving: a LabTest whose free-text ``loinc_code`` matches a
governed ``core.LoincCode`` gets its ``loinc`` FK set; the legacy CharField is
NEVER cleared (kept for audit during the transition). Unmatched rows are left
untouched. Mirrors the CID-10 reconcile (emr 0034) — the SAME helper runs from
here (historical models) and from unit tests (real models). Cross-schema FK to
the SHARED core.LoincCode, DO_NOTHING + a pre_delete protection signal.
"""

from django.db import migrations


def run_reconcile(apps, schema_editor):
    from apps.emr.loinc_backfill import reconcile_lab_test_loinc

    LabTest = apps.get_model("emr", "LabTest")
    LoincCode = apps.get_model("core", "LoincCode")
    reconcile_lab_test_loinc(LabTest, LoincCode)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0027_loinccode_ucumunit"),
        ("emr", "0040_labtest_delta_threshold_pct_labtest_loinc_and_more"),
    ]

    operations = [
        migrations.RunPython(run_reconcile, migrations.RunPython.noop),
    ]
