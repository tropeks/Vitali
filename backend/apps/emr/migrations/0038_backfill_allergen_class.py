"""E2-T2 — best-effort backfill of Allergy.allergen_class from free-text substance.

Runs the pure ``reconcile_allergies`` helper (also unit-tested directly): each
existing Allergy whose ``substance`` matches a curated ``pharmacy.AllergenClass``
(by class name or member, normalized-token) gets the FK set; unmatched rows keep
their ``substance`` and are flagged ``allergen_unmatched=True``. NEVER loses data.

Reversible as a no-op (unlinking would not restore information and the forward
pass is idempotent/re-runnable).
"""

from django.db import migrations


def backfill(apps, schema_editor):
    from apps.emr.allergen_backfill import reconcile_allergies

    Allergy = apps.get_model("emr", "Allergy")
    AllergenClass = apps.get_model("pharmacy", "AllergenClass")
    reconcile_allergies(Allergy, AllergenClass)


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0037_problem_oriented_emr"),
        ("pharmacy", "0029_nfereceipt_external_id_unique"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
