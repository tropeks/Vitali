# Generated for glosa-safety wedge PR G1 — adversarial-review fixes.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0004_glosa_safety_alert"),
    ]

    operations = [
        # FIX 1: new distinct check_code choices (engine_error / table_unresolved)
        # so the fail-open and table-unresolved advisories never collide with a
        # real "incomplete" finding on the (guide, NULL item, source) key.
        migrations.AlterField(
            model_name="glosasafetyalert",
            name="check_code",
            field=models.CharField(
                choices=[
                    ("duplicate", "Procedimento duplicado"),
                    ("stale_price", "Valor diverge da tabela vigente"),
                    ("not_in_table", "Procedimento não tabelado"),
                    ("incomplete", "Dados incompletos"),
                    ("engine_error", "Verificação indisponível"),
                    ("table_unresolved", "Cobertura não verificada"),
                ],
                max_length=20,
            ),
        ),
        # FIX 1: replace the plain unique_together (Postgres unique index treats
        # NULL guide_item as DISTINCT → duplicate guide-level rows → later
        # MultipleObjectsReturned bricks update_or_create) with a UniqueConstraint
        # using nulls_distinct=False so NULL guide_item compares EQUAL and
        # uniqueness holds for guide-level alerts too.
        migrations.AlterUniqueTogether(
            name="glosasafetyalert",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="glosasafetyalert",
            constraint=models.UniqueConstraint(
                fields=["guide", "guide_item", "check_code", "source"],
                nulls_distinct=False,
                name="uniq_glosa_alert",
            ),
        ),
    ]
