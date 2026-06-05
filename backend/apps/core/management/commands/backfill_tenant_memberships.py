"""Backfill UserTenantMembership for existing users (Model B rollout, step R1).

User/Role live in the public schema (apps.core is SHARED_APPS) and there is no
recorded user->tenant binding today. This command INFERS membership from each
tenant schema's own data: any user referenced by a FK/OneToOne to ``core.User`` in
a TENANT-app model has acted within that tenant and is granted a membership.

Run this AFTER migrating and BEFORE flipping ``ENFORCE_TENANT_MEMBERSHIP=True``;
otherwise enforcement would 401 every non-superuser. Idempotent. ``--dry-run``
reports without writing.

Users with an active account but no data footprint in any schema are reported but
NOT auto-granted (auto-granting all users to all tenants would re-open the hole).
Grant them explicitly with ``grant_tenant_membership``.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django_tenants.utils import get_tenant_model, tenant_context

from apps.core.models import UserTenantMembership

User = get_user_model()

_TENANT_APP_LABELS = {app.split(".")[-1] for app in settings.TENANT_APPS if app.startswith("apps.")}


def _user_referencing_fields(model):
    """FK / OneToOne fields on ``model`` that point at the User model."""
    fields = []
    for f in model._meta.get_fields():
        if (getattr(f, "many_to_one", False) or getattr(f, "one_to_one", False)) and (
            f.related_model is User
        ):
            fields.append(f)
    return fields


def _tenant_app_models():
    from django.apps import apps as django_apps

    models = []
    for model in django_apps.get_models():
        if model._meta.app_label in _TENANT_APP_LABELS and _user_referencing_fields(model):
            models.append(model)
    return models


class Command(BaseCommand):
    help = "Infer and create UserTenantMembership rows from per-tenant data references."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report only; do not write.")

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        Tenant = get_tenant_model()
        models = _tenant_app_models()
        self.stdout.write(
            f"Scanning {len(models)} tenant-app models with User references across tenants."
        )

        all_members = set()
        created_total = 0
        for tenant in Tenant.objects.exclude(schema_name="public"):
            user_ids = set()
            with tenant_context(tenant):
                for model in models:
                    fields = _user_referencing_fields(model)
                    # DISTINCT user ids referenced by this schema's rows.
                    for f in fields:
                        col = f"{f.name}_id"
                        ids = model._default_manager.values_list(col, flat=True)
                        user_ids.update(uid for uid in ids if uid is not None)

            user_ids.discard(None)
            all_members.update(user_ids)
            existing = set(
                UserTenantMembership.objects.filter(
                    tenant=tenant, user_id__in=user_ids
                ).values_list("user_id", flat=True)
            )
            to_create = user_ids - existing
            self.stdout.write(
                f"  {tenant.schema_name}: {len(user_ids)} referenced user(s), "
                f"{len(existing)} already bound, {len(to_create)} to create."
            )
            if not dry and to_create:
                users = User.objects.filter(pk__in=to_create)
                rows = [
                    UserTenantMembership(user=u, tenant=tenant, role=u.role, is_active=True)
                    for u in users
                ]
                UserTenantMembership.objects.bulk_create(rows, ignore_conflicts=True)
                created_total += len(rows)

        # Users with an active account but no membership anywhere — need manual grant.
        # User lives in the public schema and is reachable from any search_path, and
        # ``tenant_context`` above already restored the prior schema on exit — so we
        # must NOT force the connection to public here (it would leak across callers).
        orphaned = (
            User.objects.filter(is_active=True)
            .exclude(pk__in=all_members)
            .exclude(is_superuser=True)
            .values_list("email", flat=True)
        )
        orphaned = list(orphaned)
        if orphaned:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{len(orphaned)} active non-superuser(s) with NO data footprint in any "
                    f"tenant — NOT auto-granted. Grant explicitly with grant_tenant_membership:"
                )
            )
            for email in orphaned:
                self.stdout.write(f"    - {email}")

        verb = "Would create" if dry else "Created"
        self.stdout.write(self.style.SUCCESS(f"\n{verb} {created_total} membership(s)."))
