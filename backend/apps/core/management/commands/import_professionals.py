import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = "Import Professionals/Users from a CSV file into the specified tenant."

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

        from apps.core.models import Tenant, User
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
            email = row.get("email") or row.get("EMAIL")
            if not email or not email.strip():
                line_errors.append(f"Line {phys_line}: email missing")
            full_name = row.get("full_name") or row.get("nome")
            if not full_name or not full_name.strip():
                line_errors.append(f"Line {phys_line}: full_name missing")
            role = row.get("role") or row.get("cargo")
            if not role or not role.strip():
                line_errors.append(f"Line {phys_line}: role missing")
            hire_date = row.get("hire_date") or row.get("data_contratacao")
            if not hire_date or not hire_date.strip():
                line_errors.append(f"Line {phys_line}: hire_date missing")

        if line_errors:
            error_report = "\n".join(line_errors)
            raise CommandError(f"Import aborted — errors found:\n{error_report}")

        created = updated = 0

        # We need a system admin user to act as requesting_user for the service
        # Since it's a script, we can get the first system admin or just any admin.
        # It's better to fetch a user or pass None if allowed. We will just get the first active user of the tenant as fallback.
        from django_tenants.utils import tenant_context
        with tenant_context(tenant):
            from apps.core.models import UserTenantMembership
            try:
                admin_user = UserTenantMembership.objects.filter(tenant=tenant).first().user
            except AttributeError:
                admin_user = User.objects.first()

            from apps.hr.models import Employee
            from apps.hr.services import EmployeeOnboardingService

            with transaction.atomic():
                for row in rows:
                    email = (row.get("email") or row.get("EMAIL")).strip()
                    full_name = (row.get("full_name") or row.get("nome")).strip()
                    cpf = (row.get("cpf") or row.get("CPF") or "").strip()
                    role = (row.get("role") or row.get("cargo")).strip()
                    hire_date = (row.get("hire_date") or row.get("data_contratacao")).strip()
                    contract_type = (row.get("contract_type") or row.get("contrato") or "clt").strip()
                    council_type = (row.get("council_type") or row.get("conselho") or "").strip()
                    council_number = (row.get("council_number") or row.get("numero_conselho") or "").strip()
                    council_state = (row.get("council_state") or row.get("uf_conselho") or "").strip()
                    specialty = (row.get("specialty") or row.get("especialidade") or "").strip()

                    user_exists = User.objects.filter(email=email).first()

                    if user_exists:
                        # Idempotent: user exists
                        # Ensure tenant membership
                        UserTenantMembership.objects.get_or_create(user=user_exists, tenant=tenant)

                        # Try to update Employee
                        emp = Employee.objects.filter(user=user_exists).first()
                        if emp:
                            updated += 1
                            continue # skip if already fully created
                        else:
                            # User exists but not employee? Not supported by simple onboarding, but we could handle it.
                            # We just skip updating existing records for simplicity or we can update.
                            pass
                    else:
                        payload = {
                            "email": email,
                            "full_name": full_name,
                            "cpf": cpf,
                            "auth_mode": "invite",
                            "role": role,
                            "hire_date": hire_date,
                            "contract_type": contract_type,
                            "council_type": council_type,
                            "council_number": council_number,
                            "council_state": council_state,
                            "specialty": specialty
                        }
                        service = EmployeeOnboardingService(requesting_user=admin_user)
                        try:
                            employee = service.onboard(payload)
                            UserTenantMembership.objects.get_or_create(user=employee.user, tenant=tenant)
                            created += 1
                        except Exception as e:
                            raise CommandError(f"Failed to onboard {email}: {e}") from e

                if dry_run:
                    transaction.set_rollback(True)

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Dry run complete: {created} created, {updated} updated (skipped)"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done: {created} created, {updated} updated (skipped)"))
