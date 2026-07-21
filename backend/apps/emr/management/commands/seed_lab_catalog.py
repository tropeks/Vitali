"""Seed a conservative starter laboratory catalog for one tenant."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import tenant_context

from apps.core.models import Tenant

# Local codes are stable Vitali identifiers, not asserted LOINC/TUSS mappings.
# Reference ranges intentionally remain blank: they depend on the validated method,
# population, age and sex. Units are omitted for qualitative, panel and narrative tests.
STARTER_TESTS = (
    # Hematology
    ("HEMOGRAMA", "Hemograma completo", "hematology", "panel", "Sangue total EDTA", ""),
    ("HB", "Hemoglobina", "hematology", "numeric", "Sangue total EDTA", "g/dL"),
    ("HT", "Hematócrito", "hematology", "numeric", "Sangue total EDTA", "%"),
    ("LEU", "Leucócitos", "hematology", "numeric", "Sangue total EDTA", "/mm³"),
    ("PLAQ", "Plaquetas", "hematology", "numeric", "Sangue total EDTA", "/mm³"),
    ("RETIC", "Reticulócitos", "hematology", "numeric", "Sangue total EDTA", "%"),
    ("VHS", "Velocidade de hemossedimentação", "hematology", "numeric", "Sangue total", "mm/h"),
    # Biochemistry
    ("GLI", "Glicose", "biochemistry", "numeric", "Soro ou plasma", "mg/dL"),
    ("HBA1C", "Hemoglobina glicada (HbA1c)", "biochemistry", "numeric", "Sangue total EDTA", "%"),
    ("CRE", "Creatinina", "biochemistry", "numeric", "Soro ou plasma", "mg/dL"),
    ("URE", "Ureia", "biochemistry", "numeric", "Soro ou plasma", "mg/dL"),
    ("NA", "Sódio", "biochemistry", "numeric", "Soro ou plasma", "mmol/L"),
    ("K", "Potássio", "biochemistry", "numeric", "Soro ou plasma", "mmol/L"),
    ("CA", "Cálcio total", "biochemistry", "numeric", "Soro ou plasma", "mg/dL"),
    ("MG", "Magnésio", "biochemistry", "numeric", "Soro ou plasma", "mg/dL"),
    (
        "TGO",
        "Aspartato aminotransferase (AST/TGO)",
        "biochemistry",
        "numeric",
        "Soro ou plasma",
        "U/L",
    ),
    (
        "TGP",
        "Alanina aminotransferase (ALT/TGP)",
        "biochemistry",
        "numeric",
        "Soro ou plasma",
        "U/L",
    ),
    ("GGT", "Gama-glutamil transferase", "biochemistry", "numeric", "Soro ou plasma", "U/L"),
    ("FA", "Fosfatase alcalina", "biochemistry", "numeric", "Soro ou plasma", "U/L"),
    ("BIL", "Bilirrubinas total e frações", "biochemistry", "panel", "Soro ou plasma", ""),
    ("LIPID", "Perfil lipídico", "biochemistry", "panel", "Soro ou plasma", ""),
    ("PCR", "Proteína C-reativa", "biochemistry", "numeric", "Soro ou plasma", "mg/L"),
    # Coagulation
    ("TPINR", "Tempo de protrombina e INR", "coagulation", "panel", "Plasma citratado", ""),
    (
        "TTPA",
        "Tempo de tromboplastina parcial ativada",
        "coagulation",
        "numeric",
        "Plasma citratado",
        "s",
    ),
    ("FIB", "Fibrinogênio", "coagulation", "numeric", "Plasma citratado", "mg/dL"),
    ("DDIM", "D-dímero", "coagulation", "numeric", "Plasma citratado", ""),
    # Immunology and serology
    (
        "HIV-AGAC",
        "HIV 1/2 antígeno e anticorpos",
        "immunology",
        "qualitative",
        "Soro ou plasma",
        "",
    ),
    (
        "HBSAG",
        "Antígeno de superfície da hepatite B (HBsAg)",
        "immunology",
        "qualitative",
        "Soro ou plasma",
        "",
    ),
    ("ANTI-HCV", "Anticorpos contra hepatite C", "immunology", "qualitative", "Soro ou plasma", ""),
    (
        "SIFILIS",
        "Triagem sorológica para sífilis",
        "immunology",
        "qualitative",
        "Soro ou plasma",
        "",
    ),
    ("FAN", "Pesquisa de anticorpos antinucleares", "immunology", "text", "Soro", ""),
    ("FR", "Fator reumatoide", "immunology", "numeric", "Soro", ""),
    # Hormones
    ("TSH", "Hormônio tireoestimulante (TSH)", "hormones", "numeric", "Soro", "µUI/mL"),
    ("T4L", "Tiroxina livre (T4 livre)", "hormones", "numeric", "Soro", "ng/dL"),
    (
        "BHCG",
        "Gonadotrofina coriônica humana beta quantitativa",
        "hormones",
        "numeric",
        "Soro",
        "mUI/mL",
    ),
    ("CORT", "Cortisol", "hormones", "numeric", "Soro", "µg/dL"),
    ("PROL", "Prolactina", "hormones", "numeric", "Soro", "ng/mL"),
    # Urinalysis and parasitology
    ("EAS", "Urina tipo I (EAS)", "urinalysis", "panel", "Urina", ""),
    ("UROC", "Urocultura", "microbiology", "microbiology", "Urina", ""),
    (
        "PROT24",
        "Proteína urinária de 24 horas",
        "urinalysis",
        "numeric",
        "Urina de 24 horas",
        "mg/24 h",
    ),
    ("EPF", "Exame parasitológico de fezes", "parasitology", "text", "Fezes", ""),
    ("SOF", "Pesquisa de sangue oculto nas fezes", "parasitology", "qualitative", "Fezes", ""),
    # Microbiology
    ("HEMOC", "Hemocultura", "microbiology", "microbiology", "Sangue", ""),
    ("COPROC", "Coprocultura", "microbiology", "microbiology", "Fezes", ""),
    (
        "CULT-GERAL",
        "Cultura bacteriológica e antibiograma",
        "microbiology",
        "microbiology",
        "Material clínico",
        "",
    ),
    (
        "BAAR",
        "Pesquisa de bacilos álcool-ácido resistentes",
        "microbiology",
        "qualitative",
        "Material clínico",
        "",
    ),
    ("MICO-DIR", "Exame micológico direto", "microbiology", "text", "Material clínico", ""),
    # Toxicology
    ("TOX-URINA", "Triagem toxicológica em urina", "toxicology", "panel", "Urina", ""),
    ("ETANOL", "Etanol", "toxicology", "numeric", "Sangue total", "mg/dL"),
    ("CARBOXI", "Carboxi-hemoglobina", "toxicology", "numeric", "Sangue total", "%"),
    # Molecular and genetics
    (
        "PCR-SARS2",
        "SARS-CoV-2 por método molecular",
        "molecular",
        "qualitative",
        "Swab respiratório",
        "",
    ),
    (
        "PCR-INFLU",
        "Influenza A/B por método molecular",
        "molecular",
        "qualitative",
        "Swab respiratório",
        "",
    ),
    ("CARIOTIPO", "Cariótipo", "molecular", "text", "Sangue total heparinizado", ""),
    ("GENETICA", "Análise genética/molecular", "molecular", "text", "Material clínico", ""),
    # Pathology
    ("HISTOPAT", "Exame histopatológico", "pathology", "text", "Tecido fixado", ""),
    ("CITOPAT", "Exame citopatológico", "pathology", "text", "Material citológico", ""),
    ("IMUNO-HISTO", "Imuno-histoquímica", "pathology", "panel", "Bloco de parafina", ""),
    # Rapid tests
    ("TR-HCG", "Teste rápido de gravidez", "rapid_test", "qualitative", "Urina", ""),
    (
        "TR-HIV",
        "Teste rápido para HIV",
        "rapid_test",
        "qualitative",
        "Sangue total, soro ou plasma",
        "",
    ),
    (
        "TR-SIFILIS",
        "Teste rápido para sífilis",
        "rapid_test",
        "qualitative",
        "Sangue total, soro ou plasma",
        "",
    ),
    (
        "TR-COVID",
        "Teste rápido de antígeno para SARS-CoV-2",
        "rapid_test",
        "qualitative",
        "Swab respiratório",
        "",
    ),
)

# Component definitions describe result structure only. They deliberately contain
# neither reference intervals nor claimed standard terminology mappings.
PANEL_COMPONENTS = {
    "HEMOGRAMA": [
        {"code": "HB", "name": "Hemoglobina", "unit": "g/dL"},
        {"code": "HT", "name": "Hematócrito", "unit": "%"},
        {"code": "LEU", "name": "Leucócitos", "unit": "/mm³"},
        {"code": "PLAQ", "name": "Plaquetas", "unit": "/mm³"},
    ],
    "BIL": [
        {"code": "BIL-T", "name": "Bilirrubina total", "unit": "mg/dL"},
        {"code": "BIL-D", "name": "Bilirrubina direta", "unit": "mg/dL"},
        {"code": "BIL-I", "name": "Bilirrubina indireta", "unit": "mg/dL"},
    ],
    "LIPID": [
        {"code": "COL-T", "name": "Colesterol total", "unit": "mg/dL"},
        {"code": "HDL", "name": "Colesterol HDL", "unit": "mg/dL"},
        {"code": "LDL", "name": "Colesterol LDL", "unit": "mg/dL"},
        {"code": "TRIG", "name": "Triglicerídeos", "unit": "mg/dL"},
    ],
    "TPINR": [
        {"code": "TP", "name": "Tempo de protrombina", "unit": "s"},
        {"code": "INR", "name": "Razão normalizada internacional"},
    ],
    "EAS": [
        {"code": "ASPECTO", "name": "Aspecto"},
        {"code": "DENSIDADE", "name": "Densidade"},
        {"code": "PH", "name": "pH"},
        {"code": "PROTEINA", "name": "Proteína"},
        {"code": "GLICOSE", "name": "Glicose"},
        {"code": "SEDIMENTO", "name": "Sedimento urinário"},
    ],
}


class Command(BaseCommand):
    help = "Cria ou atualiza o catálogo laboratorial inicial de um tenant, de forma idempotente."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Schema do tenant clínico")
        parser.add_argument(
            "--dry-run", action="store_true", help="Valida e mostra o resultado sem persistir"
        )

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(schema_name=options["tenant"])
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"Tenant não encontrado: {options['tenant']}") from exc

        from apps.emr.models import LabTest

        created = updated = 0
        with tenant_context(tenant), transaction.atomic():
            for code, name, category, result_type, specimen_type, unit in STARTER_TESTS:
                _, was_created = LabTest.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "category": category,
                        "result_type": result_type,
                        "specimen_type": specimen_type,
                        "unit": unit,
                        "components": PANEL_COMPONENTS.get(code, []),
                        "active": True,
                    },
                )
                created += was_created
                updated += not was_created

            if options["dry_run"]:
                transaction.set_rollback(True)

        mode = "Dry-run" if options["dry_run"] else "Concluído"
        self.stdout.write(
            self.style.SUCCESS(f"{mode}: {created} criado(s), {updated} atualizado(s).")
        )
