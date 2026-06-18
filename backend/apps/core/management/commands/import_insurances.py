import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Import InsuranceProviders from a CSV file into the specified tenant."

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

        physical_lines = [(i + 1, ln) for i, ln in enumerate(lines) if not ln.lstrip().startswith("#") and ln.strip()]
        if not physical_lines:
            raise CommandError("CSV file is empty or contains only comments.")

        kept_texts = [ln for _, ln in physical_lines]
        reader = csv.DictReader(kept_texts, delimiter=delimiter)
        rows = list(reader)

        if not rows:
            raise CommandError("CSV file is empty or header is missing.")

        def _phys(data_idx):
            return physical_lines[data_idx + 1][0] if data_idx + 1 < len(physical_lines) else data_idx + 2

        line_errors = []
        for idx, row in enumerate(rows):
            phys_line = _phys(idx)
            ans_code = row.get("ans_code") or row.get("codigo_ans") or row.get("ANS_CODE")
            if not ans_code or not ans_code.strip():
                line_errors.append(f"Line {phys_line}: ans_code missing")

        if line_errors:
            error_report = "\n".join(line_errors)
            raise CommandError(f"Import aborted — errors found:\n{error_report}")

        created = updated = 0

        from django_tenants.utils import tenant_context
        with tenant_context(tenant):
            from apps.billing.models import InsuranceProvider
            with transaction.atomic():
                for row in rows:
                    ans_code = row.get("ans_code") or row.get("codigo_ans") or row.get("ANS_CODE")
                    ans_code = ans_code.strip()
                    name = row.get("name") or row.get("nome") or row.get("NAME") or ""
                    cnpj = row.get("cnpj") or row.get("CNPJ") or ""
                    is_active_raw = (row.get("is_active") or row.get("ativo") or "true").strip().lower()
                    is_active = is_active_raw in ("true", "1", "yes", "sim", "t", "y")

                    defaults = {
                        "name": name.strip(),
                        "cnpj": cnpj.strip(),
                        "is_active": is_active
                    }

                    obj, was_created = InsuranceProvider.objects.update_or_create(
                        ans_code=ans_code,
                        defaults=defaults
                    )
                    if was_created:
                        created += 1
                    else:
                        updated += 1

                if dry_run:
                    transaction.set_rollback(True)

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Dry run complete: {created} created, {updated} updated"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done: {created} created, {updated} updated"))
