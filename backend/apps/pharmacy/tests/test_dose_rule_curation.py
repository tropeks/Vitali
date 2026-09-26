"""
S29-02 DoseRule Curation — API test suite

Tests for the read-only DoseRule LIST endpoint and the pharmacist-only `validate`
action that sets status_validacao/validated_by/validated_at (+ ordem 028: the
CRF portrait) and writes an AuditLog.

INVIOLABLE: `validated`/`status_validacao` are NEVER serializer-writable; ONLY
the validate action mutates them.

Ordem 028: validating now ALSO requires the requesting user to have an active
``Professional(council_type="CRF")`` cadastro — a role permission
(``pharmacy.catalog_manage``) is no longer enough on its own. See
``TestValidateRequiresCRF`` below; the pre-existing ``farmaceutico`` fixture
user in this module gets one in ``setUp`` so the rest of the suite (which
exercises the permission/idempotency contract, not the CRF gate) is unaffected.
"""

from decimal import Decimal

from rest_framework.test import APIClient

from apps.core.models import AuditLog, FeatureFlag
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import Professional
from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary
from apps.test_utils import TenantTestCase


def _make_dose_rule(*, validated=False):
    """
    Build a minimal fixture: Drug → MedicationFormulary → DoseRule (fixed basis).
    Returns (drug, formulary, rule).
    """
    drug = Drug.objects.create(name="FAKE-CurationDrug", generic_name="fake_curation")
    formulary = MedicationFormulary.objects.create(
        drug=drug,
        strength_value=Decimal("10.000"),
        strength_unit="mg",
        route="PO",
        active=True,
    )
    rule = DoseRule.objects.create(
        formulary=formulary,
        basis="fixed",
        dose_unit="mg",
        min_per_dose=Decimal("5.0000"),
        max_per_dose=Decimal("20.0000"),
        absolute_max_dose=Decimal("20.0000"),
        active=True,
        validated=validated,
    )
    return drug, formulary, rule


class TestDoseRuleCurationAPI(TenantTestCase):
    def setUp(self):
        from apps.core.models import Role, User

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="pharmacy",
            defaults={"is_enabled": True},
        )
        self.role_farmaceutico = Role.objects.create(
            name="farmaceutico",
            permissions=DEFAULT_ROLES["farmaceutico"],
        )
        self.role_recepcionista = Role.objects.create(
            name="recepcionista",
            permissions=DEFAULT_ROLES["recepcionista"],
        )
        self.farmaceutico = User.objects.create_user(
            email="farm@curation.test", password="pw", role=self.role_farmaceutico
        )
        # Ordem 028: validating requires an active CRF cadastro — give this
        # fixture user one so the rest of this module (permission/idempotency
        # contract, not the CRF gate itself) is unaffected by the new check.
        Professional.objects.create(
            user=self.farmaceutico, council_type="CRF", council_number="111111", council_state="SP"
        )
        self.recepcionista = User.objects.create_user(
            email="recep@curation.test", password="pw", role=self.role_recepcionista
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    # ── List tests ────────────────────────────────────────────────────────────

    def test_list_returns_rows_with_drug_name(self):
        """GET /api/v1/pharmacy/dose-rules/ as pharmacy.read user → 200; row has drug_name + validated=False."""
        _, _, rule = _make_dose_rule(validated=False)

        resp = self._client(self.farmaceutico).get("/api/v1/pharmacy/dose-rules/")
        self.assertEqual(resp.status_code, 200)

        results = resp.data.get("results", resp.data)
        self.assertTrue(len(results) >= 1, "Expected at least one dose-rule row")

        row = next((r for r in results if str(r["id"]) == str(rule.id)), None)
        self.assertIsNotNone(row, "Created rule not found in response")
        self.assertEqual(row["drug_name"], "FAKE-CurationDrug")
        self.assertFalse(row["validated"])

    def test_list_recepcionista_403(self):
        """Recepcionista lacks pharmacy.read → 403 on dose-rules list."""
        _make_dose_rule()
        resp = self._client(self.recepcionista).get("/api/v1/pharmacy/dose-rules/")
        self.assertEqual(resp.status_code, 403)

    # ── Validate action tests ─────────────────────────────────────────────────

    def test_validate_sets_fields_and_audit(self):
        """POST /validate/ as farmaceutico → 200; rule flips to validated=True; AuditLog written."""
        _, _, rule = _make_dose_rule(validated=False)

        resp = self._client(self.farmaceutico).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 200)

        rule.refresh_from_db()
        self.assertTrue(rule.validated)
        self.assertEqual(rule.validated_by_id, self.farmaceutico.id)
        self.assertIsNotNone(rule.validated_at)

        # Exactly one AuditLog row for this action
        logs = AuditLog.objects.filter(action="dose_rule_validated", resource_id=str(rule.id))
        self.assertEqual(logs.count(), 1)

    def test_validate_already_validated_409(self):
        """POST /validate/ on a rule already validated → 409 Conflict."""
        _, _, rule = _make_dose_rule(validated=True)
        # Simulate prior validation metadata
        from django.utils import timezone

        rule.validated_by = self.farmaceutico
        rule.validated_at = timezone.now()
        rule.save(update_fields=["validated_by", "validated_at"])

        resp = self._client(self.farmaceutico).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 409)

    def test_validate_recepcionista_403(self):
        """Recepcionista lacks pharmacy.catalog_manage → 403 on validate action."""
        _, _, rule = _make_dose_rule(validated=False)

        resp = self._client(self.recepcionista).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 403)

    # ── Fix 2: PATCH write-protection regression ──────────────────────────────

    def test_doserule_patch_validated_rejected(self):
        """PATCH dose-rules/{id}/ with {"validated": true} → 403 or 405; validated still False."""
        _, _, rule = _make_dose_rule(validated=False)

        resp = self._client(self.farmaceutico).patch(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/",
            {"validated": True},
            format="json",
        )
        self.assertIn(resp.status_code, (403, 405), f"Expected 403 or 405, got {resp.status_code}")

        rule.refresh_from_db()
        self.assertFalse(rule.validated, "PATCH must not have mutated validated")


class TestValidateRequiresCRF(TenantTestCase):
    """Ordem 028: validar exige Professional(council_type='CRF', is_active=True).

    Sem CRF → 403 code=CRF_REQUIRED, regra continua nao_validado. Com CRF →
    grava o retrato (número + UF) e a data; mudar o cadastro depois NÃO muda o
    retrato já gravado.
    """

    def setUp(self):
        from apps.core.models import Role, User

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="pharmacy",
            defaults={"is_enabled": True},
        )
        role = Role.objects.create(
            name="farmaceutico-028", permissions=DEFAULT_ROLES["farmaceutico"]
        )
        self.user_sem_crf = User.objects.create_user(
            email="sem.crf@curation028.test", password="pw", role=role
        )
        self.user_com_crf = User.objects.create_user(
            email="com.crf@curation028.test", password="pw", role=role
        )
        self.professional = Professional.objects.create(
            user=self.user_com_crf,
            council_type="CRF",
            council_number="222222",
            council_state="RJ",
            is_active=True,
        )

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def test_validate_without_crf_is_403_and_rule_stays_unvalidated(self):
        _, _, rule = _make_dose_rule(validated=False)
        resp = self._client(self.user_sem_crf).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data.get("code"), "CRF_REQUIRED")
        rule.refresh_from_db()
        self.assertFalse(rule.validated)
        self.assertEqual(rule.validado_crf_numero, "")

    def test_validate_with_inactive_crf_is_403(self):
        self.professional.is_active = False
        self.professional.save(update_fields=["is_active"])
        _, _, rule = _make_dose_rule(validated=False)
        resp = self._client(self.user_com_crf).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data.get("code"), "CRF_REQUIRED")

    def test_validate_with_non_crf_council_is_403(self):
        """A CRM (medical) professional is not a pharmacist — still 403."""
        from apps.core.models import Role, User

        role = Role.objects.create(
            name="medico-028-notcrf", permissions=DEFAULT_ROLES["farmaceutico"]
        )
        doctor = User.objects.create_user(email="crm@curation028.test", password="pw", role=role)
        Professional.objects.create(
            user=doctor, council_type="CRM", council_number="333333", council_state="SP"
        )
        _, _, rule = _make_dose_rule(validated=False)
        resp = self._client(doctor).post(f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.data.get("code"), "CRF_REQUIRED")

    def test_validate_with_active_crf_records_portrait_and_audit(self):
        _, _, rule = _make_dose_rule(validated=False)
        resp = self._client(self.user_com_crf).post(
            f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        rule.refresh_from_db()
        self.assertTrue(rule.validated)
        self.assertEqual(rule.status_validacao, DoseRule.StatusValidacao.VALIDADO)
        self.assertEqual(rule.validado_crf_numero, "222222")
        self.assertEqual(rule.validado_crf_uf, "RJ")
        self.assertEqual(rule.validated_by_id, self.user_com_crf.id)
        self.assertIsNotNone(rule.validated_at)

        log = AuditLog.objects.get(action="dose_rule_validated", resource_id=str(rule.id))
        self.assertEqual(log.new_data["crf_numero"], "222222")
        self.assertEqual(log.new_data["crf_uf"], "RJ")

    def test_changing_the_cadastro_later_does_not_change_the_portrait(self):
        """The portrait is a SNAPSHOT at validation time — it must not drift
        when the Professional's own cadastro changes afterwards (renew CRF,
        move UF)."""
        _, _, rule = _make_dose_rule(validated=False)
        self._client(self.user_com_crf).post(f"/api/v1/pharmacy/dose-rules/{rule.id}/validate/")
        rule.refresh_from_db()
        self.assertEqual(rule.validado_crf_numero, "222222")
        self.assertEqual(rule.validado_crf_uf, "RJ")

        # The pharmacist renews their CRF in a different state.
        self.professional.council_number = "999999"
        self.professional.council_state = "SP"
        self.professional.save(update_fields=["council_number", "council_state"])

        rule.refresh_from_db()
        self.assertEqual(
            rule.validado_crf_numero, "222222", "o retrato não pode seguir o cadastro atual"
        )
        self.assertEqual(rule.validado_crf_uf, "RJ")
