"""
S-132: Self-serve clinic signup & subscription billing.

Covers the public signup path that replaces the per-engineer
``provision_tenant.sh`` ritual:

- ``SelfServeSignupSerializer`` validation (CNPJ check digits, formatting, email)
- provisioning helpers (slug generation + collision, domain URL derivation)
- ``SubscriptionWebhookView`` — Asaas payment events flip TRIAL → ACTIVE
- ``TenantAdminListView`` — admin panel counts + status filtering
- ``ResendWelcomeView`` — re-issue the owner's welcome link
- ``SelfServeSignupView`` — validation, duplicate-email guard, happy path,
  best-effort billing attachment

The heavy ``provision_tenant`` call (which builds a real PG schema) is mocked in
the endpoint tests so they stay fast and deterministic; the orchestration around
it — serializer, duplicate guard, response shape, billing — is what we assert.

Run: pytest apps/core/tests/test_self_serve_signup.py -v
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIClient

from apps.core.models import Plan, Role, Subscription, Tenant, User, UserTenantMembership
from apps.core.serializers import SelfServeSignupSerializer
from apps.core.services import provisioning
from apps.test_utils import TenantTestCase

# A pair of CNPJs with valid check digits (distinct so the unique constraint
# never collides across fixtures in the same test).
VALID_CNPJ_DIGITS = "11222333000181"
VALID_CNPJ_FORMATTED = "11.222.333/0001-81"
VALID_CNPJ_2 = "11444777000161"


def _schemaless_tenant(*, name, slug, status, cnpj=None, trial_days=14) -> Tenant:
    """Create a Tenant row WITHOUT provisioning a real PG schema.

    Lets the admin-list / webhook tests exercise public-schema logic cheaply —
    they never touch the tenant schema, only the public Tenant/Subscription rows.
    """
    tenant = Tenant(
        name=name,
        slug=slug,
        cnpj=cnpj,
        status=status,
        trial_ends_at=timezone.now() + datetime.timedelta(days=trial_days),
    )
    tenant.auto_create_schema = False  # per-instance override of the class default
    # django-tenants forbids creating a Tenant row outside the public schema;
    # the test runs inside the fast_test tenant, so switch back to public.
    with schema_context(get_public_schema_name()):
        tenant.save()
    return tenant


# ─── Serializer validation ────────────────────────────────────────────────────


class SelfServeSignupSerializerTests(SimpleTestCase):
    """Pure validation — no DB, no schema."""

    def _serializer(self, **overrides):
        data = {
            "company_name": "Clínica Boa Saúde",
            "cnpj": VALID_CNPJ_FORMATTED,
            "email": "Owner@Clinic.com",
        }
        data.update(overrides)
        return SelfServeSignupSerializer(data=data)

    def test_valid_payload(self):
        s = self._serializer()
        self.assertTrue(s.is_valid(), s.errors)

    def test_cnpj_is_normalized_to_formatted(self):
        s = self._serializer(cnpj=VALID_CNPJ_DIGITS)  # bare digits in
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data["cnpj"], VALID_CNPJ_FORMATTED)

    def test_email_is_lowercased(self):
        s = self._serializer(email="Owner@Clinic.com")
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(s.validated_data["email"], "owner@clinic.com")

    def test_invalid_cnpj_check_digits_rejected(self):
        s = self._serializer(cnpj="11.222.333/0001-99")
        self.assertFalse(s.is_valid())
        self.assertIn("cnpj", s.errors)

    def test_cnpj_wrong_length_rejected(self):
        s = self._serializer(cnpj="123")
        self.assertFalse(s.is_valid())
        self.assertIn("cnpj", s.errors)

    def test_repeated_digit_cnpj_rejected(self):
        s = self._serializer(cnpj="00000000000000")
        self.assertFalse(s.is_valid())
        self.assertIn("cnpj", s.errors)

    def test_blank_company_name_rejected(self):
        s = self._serializer(company_name=" ")
        self.assertFalse(s.is_valid())
        self.assertIn("company_name", s.errors)


# ─── Provisioning helpers ─────────────────────────────────────────────────────


class ProvisioningHelpersTests(TenantTestCase):
    """Slug + domain derivation (slug uniqueness needs the DB)."""

    def test_slugify_company_ascii_hyphenated(self):
        self.assertEqual(provisioning.slugify_company("Clínica Boa Saúde!!"), "cl-nica-boa-sa-de")

    def test_slugify_company_empty_falls_back(self):
        self.assertEqual(provisioning.slugify_company("   "), "clinica")

    def test_generate_unique_slug_appends_suffix_on_collision(self):
        _schemaless_tenant(name="Alpha", slug="alpha-clinica", status=Tenant.Status.TRIAL)
        slug = provisioning.generate_unique_slug("Alpha Clinica")
        self.assertNotEqual(slug, "alpha-clinica")
        self.assertTrue(slug.startswith("alpha-clinica"))
        self.assertFalse(Tenant.objects.filter(slug=slug).exists())

    def test_build_domain_url_localhost(self):
        self.assertEqual(provisioning.build_domain_url("localhost:8000", "boa"), "boa.localhost")

    def test_build_domain_url_production_strips_subdomain(self):
        self.assertEqual(provisioning.build_domain_url("app.vitali.app", "boa"), "boa.vitali.app")


# ─── Subscription webhook ─────────────────────────────────────────────────────


@override_settings(ASAAS_WEBHOOK_TOKEN="test-webhook-secret")
class SubscriptionWebhookTests(TenantTestCase):
    """Asaas recurring-payment events activate the tenant."""

    URL = "/api/v1/public/billing/subscription-webhook/"

    def setUp(self):
        self.client = APIClient()
        self.tenant = _schemaless_tenant(
            name="Webhook Clinic", slug="webhook-clinic", status=Tenant.Status.TRIAL
        )
        self.plan = Plan.objects.create(name="Starter S132", base_price="299.00", is_active=True)
        self.subscription = Subscription.objects.create(
            tenant=self.tenant,
            plan=self.plan,
            active_modules=["emr"],
            monthly_price="299.00",
            status=Subscription.Status.ACTIVE,
            current_period_start=timezone.now().date(),
            current_period_end=(timezone.now() + datetime.timedelta(days=14)).date(),
            asaas_subscription_id="sub_abc123",
        )

    def _post(self, body, token="test-webhook-secret"):
        headers = {"HTTP_ASAAS_ACCESS_TOKEN": token} if token is not None else {}
        return self.client.post(self.URL, body, format="json", **headers)

    def test_payment_received_activates_tenant(self):
        resp = self._post({"event": "PAYMENT_RECEIVED", "payment": {"subscription": "sub_abc123"}})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

    def test_invalid_token_returns_401_and_does_not_activate(self):
        resp = self._post(
            {"event": "PAYMENT_RECEIVED", "payment": {"subscription": "sub_abc123"}},
            token="wrong",
        )
        self.assertEqual(resp.status_code, 401)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.TRIAL)

    def test_unknown_subscription_is_ignored_with_200(self):
        resp = self._post(
            {"event": "PAYMENT_RECEIVED", "payment": {"subscription": "sub_does_not_exist"}}
        )
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.TRIAL)

    def test_non_activating_event_is_noop(self):
        resp = self._post({"event": "PAYMENT_OVERDUE", "payment": {"subscription": "sub_abc123"}})
        self.assertEqual(resp.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.TRIAL)

    def test_idempotent_on_duplicate_delivery(self):
        body = {"event": "PAYMENT_CONFIRMED", "payment": {"subscription": "sub_abc123"}}
        self.assertEqual(self._post(body).status_code, 200)
        self.assertEqual(self._post(body).status_code, 200)  # replay is harmless
        self.tenant.refresh_from_db()
        self.subscription.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)
        self.assertEqual(self.subscription.status, Subscription.Status.ACTIVE)


# ─── Admin tenant list ────────────────────────────────────────────────────────


class TenantAdminListTests(TenantTestCase):
    """Platform admin panel: lifecycle counts + status filtering."""

    URL = "/api/v1/platform/tenants/"

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="platform.s132@vitali.com",
            password="PlatformAdmin123!",
            full_name="Platform Admin",
        )
        self.staff = User.objects.create_user(
            email="staff.s132@clinic.com",
            password="Staff123!",
            full_name="Staff",
            role=Role.objects.create(name="admin", permissions=["users.read"]),
            is_staff=True,
        )

    def test_requires_platform_admin(self):
        self.client.force_authenticate(user=self.staff)
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_counts_reflect_created_tenants(self):
        self.client.force_authenticate(user=self.admin)
        baseline = self.client.get(self.URL).json()["counts"]

        _schemaless_tenant(name="P1", slug="pending-1", status=Tenant.Status.PENDING)
        _schemaless_tenant(name="P2", slug="pending-2", status=Tenant.Status.PENDING)
        _schemaless_tenant(name="A1", slug="active-1", status=Tenant.Status.ACTIVE)

        data = self.client.get(self.URL).json()
        self.assertEqual(data["counts"]["pending"], baseline.get("pending", 0) + 2)
        self.assertEqual(data["counts"]["active"], baseline.get("active", 0) + 1)
        self.assertEqual(data["counts"]["total"], baseline["total"] + 3)

    def test_status_filter_returns_only_matching(self):
        self.client.force_authenticate(user=self.admin)
        _schemaless_tenant(name="P1", slug="pending-only", status=Tenant.Status.PENDING)

        data = self.client.get(self.URL, {"status": "pending"}).json()
        slugs = [t["slug"] for t in data["results"]]
        self.assertIn("pending-only", slugs)
        self.assertTrue(all(t["status"] == "pending" for t in data["results"]))

    def test_row_exposes_subscription_summary(self):
        self.client.force_authenticate(user=self.admin)
        tenant = _schemaless_tenant(
            name="Billed", slug="billed-clinic", status=Tenant.Status.ACTIVE
        )
        plan = Plan.objects.create(name="Pro S132", base_price="499.00", is_active=True)
        Subscription.objects.create(
            tenant=tenant,
            plan=plan,
            active_modules=["emr"],
            monthly_price="499.00",
            status=Subscription.Status.ACTIVE,
            current_period_start=timezone.now().date(),
            current_period_end=timezone.now().date(),
            asaas_subscription_id="sub_billed",
        )
        data = self.client.get(self.URL, {"status": "active"}).json()
        row = next(t for t in data["results"] if t["slug"] == "billed-clinic")
        self.assertEqual(row["plan_name"], "Pro S132")
        self.assertEqual(row["subscription_status"], "active")
        self.assertTrue(row["has_billing"])


# ─── Resend welcome ───────────────────────────────────────────────────────────


class ResendWelcomeTests(TenantTestCase):
    """Re-issue a pending owner's set-password welcome email."""

    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="platform.resend@vitali.com",
            password="PlatformAdmin123!",
            full_name="Platform Admin",
        )
        self.client.force_authenticate(user=self.admin)
        self.tenant = _schemaless_tenant(
            name="Pending Clinic", slug="pending-clinic", status=Tenant.Status.PENDING
        )
        self.admin_role = Role.objects.create(name="admin", permissions=["admin"])
        self.owner = User.objects.create_user(
            email="owner.resend@clinic.com",
            password=None,
            full_name="Clinic Owner",
            role=self.admin_role,
        )
        UserTenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role=self.admin_role, is_active=True
        )

    def _url(self, tenant):
        return f"/api/v1/platform/tenants/{tenant.id}/resend-welcome/"

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_resends_invitation_for_owner(self, mock_send):
        from apps.core.models import UserInvitation

        resp = self.client.post(self._url(self.tenant))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()["owner_email"], self.owner.email)
        mock_send.assert_called_once()
        self.assertTrue(UserInvitation.objects.filter(user=self.owner).exists())

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_returns_404_when_no_owner(self, _mock_send):
        ownerless = _schemaless_tenant(
            name="Ownerless", slug="ownerless", status=Tenant.Status.PENDING
        )
        resp = self.client.post(self._url(ownerless))
        self.assertEqual(resp.status_code, 404)


# ─── Signup endpoint ──────────────────────────────────────────────────────────


def _fake_provision_result():
    """A ProvisionResult-shaped object that needs no real schema."""
    tenant = _schemaless_tenant(
        name="Clínica Boa Saúde", slug="clinica-boa-saude", status=Tenant.Status.PENDING
    )
    return provisioning.ProvisionResult(
        tenant=tenant,
        domain=SimpleNamespace(domain="clinica-boa-saude.localhost"),
        owner=SimpleNamespace(email="owner@clinic.com"),
        subscription=None,  # billing skipped — exercised separately
    )


class SelfServeSignupEndpointTests(TenantTestCase):
    """POST /api/v1/public/signup/ orchestration (provisioning mocked)."""

    URL = "/api/v1/public/signup/"

    def setUp(self):
        from django.core.cache import cache

        cache.clear()  # reset the AnonRateThrottle history between tests
        self.client = APIClient()

    def _payload(self, **overrides):
        data = {
            "company_name": "Clínica Boa Saúde",
            "cnpj": VALID_CNPJ_FORMATTED,
            "email": "owner@clinic.com",
        }
        data.update(overrides)
        return data

    def test_invalid_cnpj_returns_400(self):
        resp = self.client.post(self.URL, self._payload(cnpj="123"), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_duplicate_email_returns_409(self):
        User.objects.create_user(email="owner@clinic.com", password="X", full_name="Existing")
        resp = self.client.post(self.URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["error"]["code"], "EMAIL_TAKEN")

    @patch("apps.core.views_signup._attach_asaas_billing")
    @patch("apps.core.views_signup.provision_tenant")
    def test_happy_path_provisions_and_returns_201(self, mock_provision, mock_billing):
        mock_provision.return_value = _fake_provision_result()
        resp = self.client.post(self.URL, self._payload(), format="json")

        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["tenant"]["slug"], "clinica-boa-saude")
        self.assertEqual(body["tenant"]["status"], Tenant.Status.PENDING)
        self.assertEqual(body["owner_email"], "owner@clinic.com")
        self.assertEqual(body["domain"], "clinica-boa-saude.localhost")

        # Provisioning was driven from the validated payload.
        _, kwargs = mock_provision.call_args
        self.assertEqual(kwargs["owner_email"], "owner@clinic.com")
        self.assertEqual(kwargs["status"], Tenant.Status.PENDING)
        self.assertEqual(kwargs["cnpj"], VALID_CNPJ_FORMATTED)
        mock_billing.assert_called_once()

    @patch("apps.core.views_signup.provision_tenant")
    def test_provisioning_failure_returns_500(self, mock_provision):
        mock_provision.side_effect = provisioning.ProvisioningError("boom")
        resp = self.client.post(self.URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()["error"]["code"], "SIGNUP_FAILED")


class AttachAsaasBillingTests(TenantTestCase):
    """Best-effort billing attachment never blocks provisioning."""

    def setUp(self):
        self.tenant = _schemaless_tenant(
            name="Billing Clinic", slug="billing-clinic", status=Tenant.Status.PENDING
        )
        self.plan = Plan.objects.create(name="Starter B", base_price="299.00", is_active=True)
        self.subscription = Subscription.objects.create(
            tenant=self.tenant,
            plan=self.plan,
            active_modules=["emr"],
            monthly_price="299.00",
            status=Subscription.Status.ACTIVE,
            current_period_start=timezone.now().date(),
            current_period_end=(timezone.now() + datetime.timedelta(days=14)).date(),
        )

    @patch("apps.billing.services.asaas.AsaasService")
    def test_persists_asaas_ids_on_success(self, mock_service_cls):
        from apps.core.views_signup import _attach_asaas_billing

        service = mock_service_cls.return_value
        service.create_clinic_customer.return_value = "cus_123"
        service.create_subscription.return_value = {"id": "sub_999"}

        _attach_asaas_billing(
            self.subscription, tenant=self.tenant, cnpj=VALID_CNPJ_2, email="o@c.com"
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.asaas_customer_id, "cus_123")
        self.assertEqual(self.subscription.asaas_subscription_id, "sub_999")

    @patch("apps.billing.services.asaas.AsaasService")
    def test_gateway_failure_is_swallowed(self, mock_service_cls):
        from apps.core.views_signup import _attach_asaas_billing

        mock_service_cls.return_value.create_clinic_customer.side_effect = RuntimeError("down")

        # Must not raise — billing is decoupled from provisioning.
        _attach_asaas_billing(
            self.subscription, tenant=self.tenant, cnpj=VALID_CNPJ_2, email="o@c.com"
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.asaas_subscription_id, "")
