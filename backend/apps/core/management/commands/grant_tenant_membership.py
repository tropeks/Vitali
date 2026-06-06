"""Grant (or reactivate) a UserTenantMembership explicitly (Model B ops tool).

For users with no data footprint that ``backfill_tenant_memberships`` cannot infer
(e.g. a freshly created admin, read-only staff), or to add a user to an additional
clinic. Idempotent.

    manage.py grant_tenant_membership --user alice@clinic.com --tenant clinica_a
    manage.py grant_tenant_membership --user alice@clinic.com --tenant clinica_a --role admin
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_tenant_model, tenant_context

from apps.core.models import Role, UserTenantMembership

User = get_user_model()


class Command(BaseCommand):
    help = "Grant or reactivate a user's membership in a tenant."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="User email.")
        parser.add_argument("--tenant", required=True, help="Tenant schema_name.")
        parser.add_argument(
            "--role",
            default=None,
            help="Optional Role name to record on the membership (resolved in the tenant schema).",
        )

    def handle(self, *args, **opts):
        try:
            user = User.objects.get(email=opts["user"])
        except User.DoesNotExist:
            raise CommandError(f"No user with email {opts['user']!r}.") from None

        Tenant = get_tenant_model()
        try:
            tenant = Tenant.objects.get(schema_name=opts["tenant"])
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant with schema_name {opts['tenant']!r}.") from None

        role = None
        if opts["role"]:
            with tenant_context(tenant):
                role = Role.objects.filter(name=opts["role"]).first()
            if role is None:
                raise CommandError(f"No role {opts['role']!r} in tenant {tenant.schema_name}.")

        membership, created = UserTenantMembership.objects.get_or_create(
            user=user, tenant=tenant, defaults={"role": role, "is_active": True}
        )
        if not created:
            membership.is_active = True
            if role is not None:
                membership.role = role
            membership.save(update_fields=["is_active", "role"])

        verb = "Created" if created else "Reactivated/updated"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} membership: {user.email} @ {tenant.schema_name}.")
        )
