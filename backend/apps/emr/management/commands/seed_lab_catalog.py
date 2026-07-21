"""Seed a conservative starter laboratory catalog for one tenant."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import tenant_context

from apps.core.models import Tenant

# Reference ranges intentionally remain blank: they vary by method, population,
# age and sex and must be approved by the tenant's laboratory before clinical use.
STARTER_TESTS = (
    ("HB", "Hemoglobina", "Sangue total", "g/dL"),
    ("HT", "Hematócrito", "Sangue total", "%"),
    ("LEU", "Leucócitos", "Sangue total", "/mm³"),
    ("PLAQ", "Plaquetas", "Sangue total", "/mm³"),
    ("GLI", "Glicose", "Soro ou plasma", "mg/dL"),
    ("HBA1C", "Hemoglobina glicada (HbA1c)", "Sangue total", "%"),
    ("CRE", "Creatinina", "Soro ou plasma", "mg/dL"),
    ("URE", "Ureia", "Soro ou plasma", "mg/dL"),
    ("NA", "Sódio", "Soro ou plasma", "mmol/L"),
    ("K", "Potássio", "Soro ou plasma", "mmol/L"),
    ("TGO", "Aspartato aminotransferase (AST/TGO)", "Soro ou plasma", "U/L"),
    ("TGP", "Alanina aminotransferase (ALT/TGP)", "Soro ou plasma", "U/L"),
    ("PCR", "Proteína C-reativa", "Soro ou plasma", "mg/L"),
    ("TSH", "Hormônio tireoestimulante (TSH)", "Soro", "µUI/mL"),
    ("T4L", "Tiroxina livre (T4 livre)", "Soro", "ng/dL"),
    ("EAS", "Urina tipo I (EAS)", "Urina", ""),
)


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
            for code, name, specimen_type, unit in STARTER_TESTS:
                _, was_created = LabTest.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "specimen_type": specimen_type,
                        "unit": unit,
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
