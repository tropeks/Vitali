import csv
import logging
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import Patients from a CSV file into the specified tenant."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the CSV file")
        parser.add_argument("--tenant", required=True, help="Tenant schema context")
        parser.add_argument("--delimiter", default=";", help="CSV column delimiter")
        parser.add_argument("--dry-run", action="store_true", help="Validate without writing")

    def handle(self, *args, **options):
        csv_path = Path(options["file"])
        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        schema = options["tenant"]
        delimiter = options["delimiter"]
        dry_run = options["dry_run"]

        from apps.core.models import Tenant

        try:
            tenant = Tenant.objects.get(schema_name=schema)
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"Tenant not found: {schema}") from exc

        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            lines = list(fh)

        physical_lines = [
            (i + 1, ln)
            for i, ln in enumerate(lines)
            if not ln.lstrip().startswith("#") and ln.strip()
        ]
        if not physical_lines:
            raise CommandError("CSV file is empty or contains only comments.")

        kept_texts = [ln for _, ln in physical_lines]
        reader = csv.DictReader(kept_texts, delimiter=delimiter)
        rows = list(reader)

        if not rows:
            raise CommandError("CSV file is empty or header is missing.")

        def _phys(data_idx):
            return (
                physical_lines[data_idx + 1][0]
                if data_idx + 1 < len(physical_lines)
                else data_idx + 2
            )

        line_errors = []
        for idx, row in enumerate(rows):
            phys_line = _phys(idx)
            cpf = row.get("cpf") or row.get("CPF")
            if not cpf or not cpf.strip():
                line_errors.append(f"Line {phys_line}: cpf missing")
            full_name = row.get("full_name") or row.get("nome") or row.get("nome_completo")
            if not full_name or not full_name.strip():
                line_errors.append(f"Line {phys_line}: full_name missing")
            birth_date = row.get("birth_date") or row.get("data_nascimento")
            if not birth_date or not birth_date.strip():
                line_errors.append(f"Line {phys_line}: birth_date missing")
            else:
                try:
                    datetime.strptime(birth_date.strip(), "%Y-%m-%d")
                except ValueError:
                    line_errors.append(
                        f"Line {phys_line}: birth_date invalid format, expected YYYY-MM-DD"
                    )

        if line_errors:
            error_report = "\n".join(line_errors)
            raise CommandError(f"Import aborted — errors found:\n{error_report}")

        created = updated = 0

        from django_tenants.utils import tenant_context

        with tenant_context(tenant):
            from apps.emr.models import Patient

            with transaction.atomic():
                existing_patients = {p.cpf: p for p in Patient.objects.all() if p.cpf}

                for row in rows:
                    cpf = (row.get("cpf") or row.get("CPF")).strip()
                    full_name = (
                        row.get("full_name") or row.get("nome") or row.get("nome_completo")
                    ).strip()
                    birth_date_str = (row.get("birth_date") or row.get("data_nascimento")).strip()
                    birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
                    gender = (row.get("gender") or row.get("sexo") or "N").strip().upper()
                    phone = (row.get("phone") or row.get("telefone") or "").strip()
                    email = (row.get("email") or row.get("EMAIL") or "").strip()

                    p = existing_patients.get(cpf)
                    if p:
                        p.full_name = full_name
                        p.birth_date = birth_date
                        p.gender = gender
                        p.phone = phone
                        p.email = email
                        p.save()
                        updated += 1
                    else:
                        Patient.objects.create(
                            cpf=cpf,
                            full_name=full_name,
                            birth_date=birth_date,
                            gender=gender,
                            phone=phone,
                            email=email,
                        )
                        created += 1

                if dry_run:
                    transaction.set_rollback(True)

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"Dry run complete: {created} created, {updated} updated")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Done: {created} created, {updated} updated"))
