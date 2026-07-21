"""
Management command: bootstrap_beta
Usage:
    python manage.py bootstrap_beta \
        --public-domain vitali.example.com \
        --clinic-slug demo --clinic-name "Clínica Demo" \
        --clinic-domain demo-clinic.example.com \
        --admin-email admin@example.com

Bootstraps a fresh environment (beta/staging/local) end to end:
public tenant + routing domain, one clinic tenant + routing domain,
default roles in the clinic schema, a clinic admin, and an active beta
subscription whose module flags match the selected MVP package.

Safe to run multiple times — every step is get_or_create/idempotent.
The admin password is read from the BOOTSTRAP_ADMIN_PASSWORD environment
variable (never a CLI argument, so it stays out of shell history and
``ps`` output); if unset and the admin does not exist yet, the command
fails loudly instead of inventing a credential.

This replaces the inline ``manage.py shell -c`` blobs previously
duplicated between the CI e2e workflow and manual deploy runbooks —
see docs/DEPLOY.md ("Beta via Cloudflare Tunnel").
"""

import os
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from apps.core.constants import ALLOWED_MODULE_KEYS

DEFAULT_BETA_MODULES = (
    "emr",
    "billing",
    "pharmacy",
    "whatsapp",
    "ai_tuss",
    "analytics",
    "rh",
)


class Command(BaseCommand):
    help = "Bootstrap public + clinic tenants, roles and a clinic admin for a fresh environment."

    def add_arguments(self, parser):
        parser.add_argument(
            "--public-domain",
            required=True,
            help="Primary routing domain for the public schema (e.g. vitali.example.com).",
        )
        parser.add_argument(
            "--clinic-slug",
            default="demo",
            help="Slug/schema name for the clinic tenant (default: demo).",
        )
        parser.add_argument(
            "--clinic-name",
            default="Clínica Demo",
            help='Display name for the clinic tenant (default: "Clínica Demo").',
        )
        parser.add_argument(
            "--clinic-domain",
            action="append",
            default=None,
            help=(
                "Routing domain for the clinic tenant. Repeatable; the first one is primary. "
                "Defaults to <clinic-slug>.<public-domain>. NOTE: on Cloudflare free plans the "
                "universal certificate only covers ONE subdomain level — prefer a first-level "
                "host (e.g. vitali-demo.example.com) when serving through a CF tunnel."
            ),
        )
        parser.add_argument(
            "--admin-email",
            default=None,
            help="Clinic admin e-mail. If omitted, no admin user is created.",
        )
        parser.add_argument(
            "--admin-name",
            default="Admin",
            help='Full name for the clinic admin (default: "Admin").',
        )
        parser.add_argument(
            "--plan-name",
            default="Beta MVP",
            help='Subscription plan name (default: "Beta MVP").',
        )
        parser.add_argument(
            "--plan-price",
            type=Decimal,
            default=Decimal("0.00"),
            help="Monthly beta price in BRL (default: 0.00).",
        )
        parser.add_argument(
            "--subscription-days",
            type=int,
            default=365,
            help="Subscription period in days from today (default: 365).",
        )
        parser.add_argument(
            "--module",
            action="append",
            dest="modules",
            choices=sorted(ALLOWED_MODULE_KEYS),
            help=(
                "Active module key. Repeatable. When omitted, provisions the agreed beta MVP "
                f"package: {', '.join(DEFAULT_BETA_MODULES)}."
            ),
        )

    def handle(self, *args, **options):
        # Management commands may be invoked while another schema is selected
        # (notably tests and operational shells). Shared provisioning records
        # must always be read/written through the public schema.
        with schema_context(get_public_schema_name()):
            self._bootstrap(options)

    def _bootstrap(self, options):
        from apps.core.models import (
            Domain,
            FeatureFlag,
            Plan,
            PlanModule,
            Role,
            Subscription,
            Tenant,
            User,
            UserTenantMembership,
        )

        public_domain = options["public_domain"]
        clinic_slug = options["clinic_slug"]
        clinic_name = options["clinic_name"]
        clinic_domains = options["clinic_domain"] or [f"{clinic_slug}.{public_domain}"]
        admin_email = options["admin_email"]
        admin_name = options["admin_name"]
        plan_name = options["plan_name"]
        plan_price = options["plan_price"]
        subscription_days = options["subscription_days"]
        modules = list(dict.fromkeys(options["modules"] or DEFAULT_BETA_MODULES))

        if plan_price < 0:
            raise CommandError("--plan-price must be zero or greater.")
        if subscription_days < 1:
            raise CommandError("--subscription-days must be at least 1.")

        # Tenant.save() copies slug → schema_name; look up by slug (unique).
        public, created = Tenant.objects.get_or_create(slug="public", defaults={"name": "public"})
        self._report("public tenant", created)
        _, created = Domain.objects.get_or_create(
            domain=public_domain, defaults={"tenant": public, "is_primary": True}
        )
        self._report(f"public domain {public_domain}", created)

        clinic, created = Tenant.objects.get_or_create(
            slug=clinic_slug, defaults={"name": clinic_name}
        )
        self._report(f"clinic tenant {clinic_slug}", created)
        for i, dom in enumerate(clinic_domains):
            _, created = Domain.objects.get_or_create(
                domain=dom, defaults={"tenant": clinic, "is_primary": i == 0}
            )
            self._report(f"clinic domain {dom}", created)

        call_command("create_default_roles", schema=clinic.schema_name)

        if admin_email:
            with schema_context(clinic.schema_name):
                admin = User.objects.filter(email=admin_email).first()
                if admin is None:
                    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
                    if not password:
                        raise CommandError(
                            "BOOTSTRAP_ADMIN_PASSWORD env var is required to create "
                            f"the admin user {admin_email} (never passed via CLI args)."
                        )
                    admin_role = Role.objects.get(name="admin")
                    admin = User.objects.create_user(
                        email=admin_email,
                        password=password,
                        full_name=admin_name,
                        role=admin_role,
                        is_active=True,
                        is_staff=True,
                        is_superuser=False,
                    )
                    self._report(f"admin {admin_email}", created=True)
                else:
                    admin_role = Role.objects.get(name="admin")
                    # Repair old beta bootstraps which accidentally granted the
                    # clinic owner platform-wide superuser powers.
                    changed_fields = []
                    for field, value in (
                        ("role", admin_role),
                        ("is_active", True),
                        ("is_staff", True),
                        ("is_superuser", False),
                    ):
                        if getattr(admin, field) != value:
                            setattr(admin, field, value)
                            changed_fields.append(field)
                    if changed_fields:
                        admin.save(update_fields=changed_fields)
                    self._report(f"admin {admin_email}", created=False)

                membership, membership_created = UserTenantMembership.objects.get_or_create(
                    user=admin,
                    tenant=clinic,
                    defaults={"role": admin_role, "is_active": True},
                )
                membership_updates = []
                if membership.role_id != admin_role.id:
                    membership.role = admin_role
                    membership_updates.append("role")
                if not membership.is_active:
                    membership.is_active = True
                    membership_updates.append("is_active")
                if membership_updates:
                    membership.save(update_fields=membership_updates)
                self._report(f"admin membership {admin_email}", membership_created)

        plan, plan_created = Plan.objects.get_or_create(
            name=plan_name,
            defaults={"base_price": plan_price, "is_active": True},
        )
        plan_updates = []
        if plan.base_price != plan_price:
            plan.base_price = plan_price
            plan_updates.append("base_price")
        if not plan.is_active:
            plan.is_active = True
            plan_updates.append("is_active")
        if plan_updates:
            plan.save(update_fields=plan_updates)
        self._report(f"plan {plan_name}", plan_created)

        # Reconcile the plan itself as well as the tenant flags. Without this,
        # rerunning with a narrower --module selection leaves stale modules
        # advertised as included in the commercial plan.
        PlanModule.objects.filter(plan=plan).exclude(module_key__in=modules).update(
            is_included=False
        )
        for module_key in modules:
            PlanModule.objects.update_or_create(
                plan=plan,
                module_key=module_key,
                defaults={"price": Decimal("0.00"), "is_included": True},
            )

        today = timezone.localdate()
        subscription, subscription_created = Subscription.objects.update_or_create(
            tenant=clinic,
            defaults={
                "plan": plan,
                "active_modules": modules,
                "monthly_price": plan_price,
                "status": Subscription.Status.ACTIVE,
                "current_period_start": today,
                "current_period_end": today + timedelta(days=subscription_days),
            },
        )
        self._report(f"subscription {clinic_slug}", subscription_created)

        # Keep the API/menu source of truth exactly aligned with the subscription.
        # This also leaves safety wedges OFF unless an operator explicitly passes
        # them via --module after completing their required governance setup.
        FeatureFlag.objects.filter(tenant=clinic).exclude(module_key__in=modules).update(
            is_enabled=False
        )
        for module_key in modules:
            FeatureFlag.objects.update_or_create(
                tenant=clinic,
                module_key=module_key,
                defaults={"is_enabled": True},
            )
        self.stdout.write(f"  active modules: {', '.join(subscription.active_modules)}")

        self.stdout.write(self.style.SUCCESS("Bootstrap complete."))

    def _report(self, what: str, created: bool):
        verb = "created" if created else "exists"
        self.stdout.write(f"  {what}: {verb}")
