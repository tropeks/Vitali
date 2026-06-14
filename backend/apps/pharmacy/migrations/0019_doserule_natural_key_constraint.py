# Generated manually for S29 audit fix — add full natural-key UniqueConstraint
# to DoseRule so that banded rules (differing only by age/weight band) can coexist
# and the import_formulary upsert is backed by a real DB constraint.
#
# nulls_distinct=False: NULL band values compare equal so two rules that are
# identical except for both having NULL in the same band column are treated as
# the same row (Postgres legacy UNIQUE treats NULL as distinct — nulls_distinct=False
# fixes that). Requires Django 5.0+ + PostgreSQL 15+; both in use (Django 5.2, PG 16).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pharmacy", "0018_allergen_interaction_provenance"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="doserule",
            constraint=models.UniqueConstraint(
                fields=[
                    "formulary",
                    "basis",
                    "dose_role",
                    "route",
                    "freq_min_per_day",
                    "freq_max_per_day",
                    "age_min_days",
                    "age_max_days",
                    "weight_min_kg",
                    "weight_max_kg",
                ],
                name="doserule_natural_key",
                nulls_distinct=False,
            ),
        ),
    ]
