"""E1-T5 — migrate loose CID-10 usage to governed FK/M2M on core.CID10Code.

* MedicalHistory.cid10_code (CharField) → cid10 FK + legacy_cid_text + flag.
* SOAPNote.cid10_codes (JSON list)      → cid10 M2M (via SOAPNoteCID10 through)
                                          + legacy_cid_codes + flag.
Data is reconciled best-effort (matched → FK/M2M, unmatched → preserved raw +
flag) so nothing is ever lost. Cross-schema FKs mirror EncounterProcedure→TUSS
(DO_NOTHING + pre_delete protection signal).
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


def run_reconcile(apps, schema_editor):
    from apps.emr.cid_backfill import reconcile_medical_history, reconcile_soap_note

    MedicalHistory = apps.get_model("emr", "MedicalHistory")
    SOAPNote = apps.get_model("emr", "SOAPNote")
    SOAPNoteCID10 = apps.get_model("emr", "SOAPNoteCID10")
    CID10Code = apps.get_model("core", "CID10Code")
    reconcile_medical_history(MedicalHistory, CID10Code)
    reconcile_soap_note(SOAPNote, CID10Code, SOAPNoteCID10)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0024_cid10_rich"),
        ("emr", "0033_enterprise_diagnostics"),
    ]

    operations = [
        # ── MedicalHistory: CharField → FK ────────────────────────────────────
        migrations.RenameField(
            model_name="medicalhistory",
            old_name="cid10_code",
            new_name="legacy_cid_text",
        ),
        migrations.AlterField(
            model_name="medicalhistory",
            name="legacy_cid_text",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Código CID-10 bruto não reconciliado com core.CID10Code.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="medicalhistory",
            name="cid10",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="core.cid10code",
                verbose_name="CID-10",
            ),
        ),
        migrations.AddField(
            model_name="medicalhistory",
            name="cid_unmatched",
            field=models.BooleanField(
                default=False,
                help_text="True quando legacy_cid_text não corresponde a nenhum CID10Code governado.",
            ),
        ),
        # ── SOAPNote: JSON list → M2M ─────────────────────────────────────────
        migrations.RenameField(
            model_name="soapnote",
            old_name="cid10_codes",
            new_name="legacy_cid_codes",
        ),
        migrations.AlterField(
            model_name="soapnote",
            name="legacy_cid_codes",
            field=models.JSONField(
                default=list,
                help_text="Códigos CID-10 brutos não reconciliados com core.CID10Code.",
            ),
        ),
        migrations.CreateModel(
            name="SOAPNoteCID10",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "soap_note",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cid10_links",
                        to="emr.soapnote",
                    ),
                ),
                (
                    "cid10",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="core.cid10code",
                    ),
                ),
            ],
            options={
                "verbose_name": "Vínculo SOAP–CID10",
                "verbose_name_plural": "Vínculos SOAP–CID10",
                "unique_together": {("soap_note", "cid10")},
            },
        ),
        migrations.AddField(
            model_name="soapnote",
            name="cid10",
            field=models.ManyToManyField(
                blank=True,
                related_name="+",
                through="emr.SOAPNoteCID10",
                to="core.cid10code",
                verbose_name="CID-10",
            ),
        ),
        migrations.AddField(
            model_name="soapnote",
            name="cid_unmatched",
            field=models.BooleanField(
                default=False, help_text="True quando há códigos em legacy_cid_codes."
            ),
        ),
        migrations.RunPython(run_reconcile, migrations.RunPython.noop),
    ]
