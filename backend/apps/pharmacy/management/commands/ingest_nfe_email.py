from pathlib import Path

from django.core.management.base import BaseCommand

from apps.pharmacy.services.nfe_ingestion import ingest_xml


class Command(BaseCommand):
    help = "Ingere XMLs recebidos pela caixa de e-mail em quarentena (não lança estoque)."

    def add_arguments(self, parser):
        parser.add_argument("directory", type=Path)

    def handle(self, *args, **options):
        directory = options["directory"]
        for path in sorted(directory.glob("*.xml")):
            try:
                receipt, created = ingest_xml(
                    path.read_bytes(), source="email", external_id=path.name
                )
                self.stdout.write(
                    f"{path.name}: {receipt.id} ({'novo' if created else 'duplicado'})"
                )
            except ValueError as exc:
                self.stderr.write(f"{path.name}: quarentena ({exc})")
