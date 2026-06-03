# Generated for glosa wedge G3d — authorization-required check + Authorization model.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0007_pricetableitem_max_per_procedure_and_quantity_exceeds"),
        ("core", "0001_initial"),
        ("emr", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="pricetableitem",
            name="requires_authorization",
            field=models.BooleanField(
                default=False,
                help_text="Se marcado, o procedimento exige autorização (senha) válida para faturar.",
                verbose_name="Exige autorização prévia",
            ),
        ),
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
                    ("clinical_incompat", "Incompatibilidade clínica"),
                    ("quantity_exceeds", "Quantidade acima do teto"),
                    ("authorization_missing", "Autorização ausente"),
                ],
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="Authorization",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("valid_from", models.DateField(verbose_name="Válida a partir de")),
                (
                    "valid_until",
                    models.DateField(
                        blank=True,
                        help_text="Vazio = sem data de término (autorização em aberto).",
                        null=True,
                        verbose_name="Válida até",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendente"),
                            ("approved", "Aprovada"),
                            ("denied", "Negada"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=10,
                        verbose_name="Status",
                    ),
                ),
                (
                    "authorization_number",
                    models.CharField(
                        blank=True, max_length=20, verbose_name="Número da autorização"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="authorizations",
                        to="emr.patient",
                    ),
                ),
                (
                    "provider",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="authorizations",
                        to="billing.insuranceprovider",
                    ),
                ),
                (
                    "tuss_code",
                    models.ForeignKey(
                        blank=True,
                        help_text="Procedimento autorizado. Vazio = autorização genérica (qualquer procedimento).",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authorizations",
                        to="core.tusscode",
                    ),
                ),
            ],
            options={
                "verbose_name": "Autorização",
                "verbose_name_plural": "Autorizações",
                "ordering": ["-valid_from"],
            },
        ),
        migrations.AddIndex(
            model_name="authorization",
            index=models.Index(
                fields=["patient", "provider", "status"],
                name="billing_aut_patient_3fe7dc_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="authorization",
            index=models.Index(fields=["tuss_code"], name="billing_aut_tuss_co_6a6674_idx"),
        ),
        migrations.AddIndex(
            model_name="authorization",
            index=models.Index(
                fields=["valid_from", "valid_until"],
                name="billing_aut_valid_f_9f34d2_idx",
            ),
        ),
    ]
