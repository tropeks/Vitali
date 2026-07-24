"""E4-T2: seed one anchor specialty template — Clínica Geral anamnese.

apps.emr is a TENANT_APP: migrate_schemas runs this migration once per
tenant schema (same pattern as 0026's RunPython), so every existing and
future tenant gets the seeded, published template — no manual tenant loop
needed.

The template is created already published (frozen): any future content
change goes through ``ClinicalFormTemplate.new_version`` rather than editing
this row in place, matching the "immutable once published" contract from
E4-T1.
"""

from django.db import migrations
from django.utils import timezone

TEMPLATE_NAME = "Anamnese — Clínica Geral"
TEMPLATE_SPECIALTY = "clinica_geral"

# Content authored by a human (clinical curation), not generated — the schema
# shape/validation itself (E4-T1) is what's automated.
ANAMNESIS_SCHEMA = [
    {
        "key": "chief_complaint",
        "label": "Queixa principal",
        "type": "textarea",
        "required": True,
    },
    {
        "key": "history_of_present_illness",
        "label": "História da doença atual",
        "type": "textarea",
        "required": True,
    },
    {
        "key": "known_allergies",
        "label": "Alergias conhecidas",
        "type": "textarea",
        "required": False,
    },
    {
        "key": "current_medications",
        "label": "Medicamentos em uso contínuo",
        "type": "textarea",
        "required": False,
    },
    {
        "key": "comorbidities",
        "label": "Comorbidades",
        "type": "multiselect",
        "required": False,
        "options": [
            "hipertensão",
            "diabetes",
            "dislipidemia",
            "cardiopatia",
            "asma/DPOC",
            "doença renal crônica",
            "hipotireoidismo",
            "nenhuma",
        ],
    },
    {
        "key": "smoker",
        "label": "Tabagista?",
        "type": "boolean",
        "required": True,
    },
    {
        "key": "alcohol_use",
        "label": "Uso de álcool",
        "type": "select",
        "required": False,
        "options": ["nunca", "social", "frequente"],
    },
    {
        "key": "family_history",
        "label": "Antecedentes familiares relevantes",
        "type": "textarea",
        "required": False,
    },
    {
        "key": "notes",
        "label": "Observações adicionais",
        "type": "textarea",
        "required": False,
    },
]


def seed_anamnesis_template(apps, schema_editor):
    ClinicalFormTemplate = apps.get_model("emr", "ClinicalFormTemplate")
    if ClinicalFormTemplate.objects.filter(
        name=TEMPLATE_NAME, specialty=TEMPLATE_SPECIALTY
    ).exists():
        return
    ClinicalFormTemplate.objects.create(
        name=TEMPLATE_NAME,
        specialty=TEMPLATE_SPECIALTY,
        version=1,
        schema=ANAMNESIS_SCHEMA,
        active=True,
        is_published=True,
        published_at=timezone.now(),
    )


def remove_anamnesis_template(apps, schema_editor):
    ClinicalFormTemplate = apps.get_model("emr", "ClinicalFormTemplate")
    ClinicalFormTemplate.objects.filter(
        name=TEMPLATE_NAME, specialty=TEMPLATE_SPECIALTY, version=1
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("emr", "0034_clinicalformtemplate_clinicalformresponse"),
    ]

    operations = [
        migrations.RunPython(seed_anamnesis_template, remove_anamnesis_template),
    ]
