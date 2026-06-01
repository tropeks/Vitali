"""
F-03 PR1 — EncounterProcedure model + nested REST + cross-schema PROTECT signal.

Covers:
- create/list procedures on an OPEN encounter (201, persisted fields)
- write gate: create/update/delete on a SIGNED encounter → 409
- quantity 0 / negative → rejected
- inactive TUSS code → rejected (create + update)
- protect signal blocks deleting a TUSSCode referenced by an EncounterProcedure
- nested CRUD permission split (emr.write for writes, emr.read for reads)
- multi-tenant isolation (procedure in tenant A invisible in tenant B)
- cross-schema FK to core.TUSSCode resolves (select_related)
"""

from decimal import Decimal

from django.db.models.deletion import ProtectedError
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIClient

from apps.core.models import TUSSCode
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import Encounter, EncounterProcedure, Patient, Professional
from apps.test_utils import TenantTestCase


def _make_tuss(code="10101012", active=True):
    return TUSSCode.objects.create(
        code=code,
        description="Consulta em consultório",
        group="procedimento",
        version="2024-01",
        active=active,
    )


def _make_infra():
    from apps.core.models import Role, User

    role_md = Role.objects.create(name="medico_ep", permissions=DEFAULT_ROLES["medico"])
    role_enf = Role.objects.create(name="enfermeiro_ep", permissions=DEFAULT_ROLES["enfermeiro"])
    medico_user = User.objects.create_user(email="md_ep@t.com", password="pw", role=role_md)
    enf_user = User.objects.create_user(email="enf_ep@t.com", password="pw", role=role_enf)
    patient = Patient.objects.create(
        full_name="Procedure Patient", birth_date="1985-06-15", gender="F", cpf="33333333333"
    )
    prof = Professional.objects.create(
        user=medico_user, council_type="CRM", council_number="9", council_state="SP"
    )
    encounter = Encounter.objects.create(patient=patient, professional=prof)
    return medico_user, enf_user, patient, prof, encounter


class TestEncounterProcedureModel(TenantTestCase):
    def setUp(self):
        self.medico_user, self.enf_user, self.patient, self.prof, self.encounter = _make_infra()
        self.tuss = _make_tuss()

    def test_create_procedure_persists_fields(self):
        proc = EncounterProcedure.objects.create(
            encounter=self.encounter,
            tuss_code=self.tuss,
            quantity=Decimal("2.00"),
            performed_by=self.prof,
            notes="bilateral",
        )
        proc.refresh_from_db()
        self.assertEqual(proc.encounter_id, self.encounter.id)
        self.assertEqual(proc.tuss_code_id, self.tuss.id)
        self.assertEqual(proc.quantity, Decimal("2.00"))
        # unit_value is a deferred cache hint — null in PR1.
        self.assertIsNone(proc.unit_value)

    def test_cross_schema_fk_resolves_with_select_related(self):
        EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        proc = EncounterProcedure.objects.select_related("tuss_code").get(encounter=self.encounter)
        self.assertEqual(proc.tuss_code.code, self.tuss.code)


class TestEncounterProcedureAPI(TenantTestCase):
    def setUp(self):
        self.medico_user, self.enf_user, self.patient, self.prof, self.encounter = _make_infra()
        self.tuss = _make_tuss()

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _url(self, proc_id=None):
        base = f"/api/v1/encounters/{self.encounter.id}/procedures/"
        return f"{base}{proc_id}/" if proc_id else base

    def test_create_on_open_encounter_returns_201(self):
        resp = self._client(self.medico_user).post(
            self._url(),
            {"tuss_code": self.tuss.id, "quantity": "2", "notes": "ok"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        proc = EncounterProcedure.objects.get(id=resp.data["id"])
        self.assertEqual(proc.encounter_id, self.encounter.id)
        self.assertEqual(proc.tuss_code_id, self.tuss.id)
        self.assertEqual(resp.data["tuss_code_detail"]["code"], self.tuss.code)

    def test_list_returns_procedures(self):
        EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        resp = self._client(self.medico_user).get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)

    def test_create_on_signed_encounter_rejected(self):
        self.encounter.status = "signed"
        self.encounter.save(update_fields=["status"])
        resp = self._client(self.medico_user).post(
            self._url(), {"tuss_code": self.tuss.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data["error"]["code"], "ENCOUNTER_NOT_OPEN")

    def test_update_on_signed_encounter_rejected(self):
        proc = EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        self.encounter.status = "signed"
        self.encounter.save(update_fields=["status"])
        resp = self._client(self.medico_user).patch(
            self._url(proc.id), {"quantity": "3"}, format="json"
        )
        self.assertEqual(resp.status_code, 409)

    def test_delete_on_signed_encounter_rejected(self):
        proc = EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        self.encounter.status = "signed"
        self.encounter.save(update_fields=["status"])
        resp = self._client(self.medico_user).delete(self._url(proc.id))
        self.assertEqual(resp.status_code, 409)

    def test_update_and_delete_on_open_encounter_succeed(self):
        proc = EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        client = self._client(self.medico_user)
        patch_resp = client.patch(self._url(proc.id), {"quantity": "4"}, format="json")
        self.assertEqual(patch_resp.status_code, 200)
        proc.refresh_from_db()
        self.assertEqual(proc.quantity, Decimal("4.00"))
        del_resp = client.delete(self._url(proc.id))
        self.assertEqual(del_resp.status_code, 204)
        self.assertFalse(EncounterProcedure.objects.filter(id=proc.id).exists())

    def test_quantity_zero_rejected(self):
        resp = self._client(self.medico_user).post(
            self._url(), {"tuss_code": self.tuss.id, "quantity": "0"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("quantity", resp.data)

    def test_quantity_negative_rejected(self):
        resp = self._client(self.medico_user).post(
            self._url(), {"tuss_code": self.tuss.id, "quantity": "-1"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("quantity", resp.data)

    def test_inactive_tuss_code_rejected_on_create(self):
        inactive = _make_tuss(code="99999999", active=False)
        resp = self._client(self.medico_user).post(
            self._url(), {"tuss_code": inactive.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("tuss_code", resp.data)

    def test_inactive_tuss_code_rejected_on_update(self):
        proc = EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        inactive = _make_tuss(code="99999998", active=False)
        resp = self._client(self.medico_user).patch(
            self._url(proc.id), {"tuss_code": inactive.id}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("tuss_code", resp.data)

    def test_patch_quantity_only_on_active_code_allowed(self):
        """Fix 2: PATCH that omits tuss_code (only quantity/notes) on a procedure
        whose code is still active must NOT be rejected by the inactive-TUSS check."""
        proc = EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        resp = self._client(self.medico_user).patch(
            self._url(proc.id), {"quantity": "5", "notes": "revised"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        proc.refresh_from_db()
        self.assertEqual(proc.quantity, Decimal("5.00"))
        self.assertEqual(proc.notes, "revised")

    def test_unit_value_is_read_only(self):
        """unit_value is a deferred cache hint; client cannot set it in PR1."""
        resp = self._client(self.medico_user).post(
            self._url(),
            {"tuss_code": self.tuss.id, "quantity": "1", "unit_value": "150.00"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        proc = EncounterProcedure.objects.get(id=resp.data["id"])
        self.assertIsNone(proc.unit_value)

    # ─── Permission split ──────────────────────────────────────────────────

    def test_read_allowed_for_emr_read_only_role(self):
        """enfermeiro has emr.read (no emr.write) → GET allowed."""
        EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        resp = self._client(self.enf_user).get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_write_forbidden_for_emr_read_only_role(self):
        """enfermeiro has no emr.write → POST forbidden."""
        resp = self._client(self.enf_user).post(
            self._url(), {"tuss_code": self.tuss.id, "quantity": "1"}, format="json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_delete_forbidden_for_emr_read_only_role(self):
        proc = EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        resp = self._client(self.enf_user).delete(self._url(proc.id))
        self.assertEqual(resp.status_code, 403)


class TestEncounterStatusImmutableViaPatch(TenantTestCase):
    """Fix 1 (CRITICAL): Encounter.status must NOT be client-mutable via a generic
    PATCH. Allowing it would let an emr.write client flip a signed encounter back to
    "open", mutate its procedures, and re-sign — defeating the procedure write-gate
    and CFM signature integrity. Status changes ONLY through the dedicated sign action.
    """

    def setUp(self):
        self.medico_user, self.enf_user, self.patient, self.prof, self.encounter = _make_infra()

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    def _detail_url(self):
        return f"/api/v1/encounters/{self.encounter.id}/"

    def test_patch_status_is_ignored_on_open_encounter(self):
        """PATCH {"status": "signed"} on an open encounter is ignored — stays open."""
        resp = self._client(self.medico_user).patch(
            self._detail_url(), {"status": "signed"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.encounter.refresh_from_db()
        self.assertEqual(self.encounter.status, "open")
        self.assertIsNone(self.encounter.signed_at)

    def test_patch_cannot_reopen_signed_encounter(self):
        """A signed encounter cannot be flipped back to "open" via generic PATCH."""
        self.encounter.status = "signed"
        self.encounter.save(update_fields=["status"])
        resp = self._client(self.medico_user).patch(
            self._detail_url(), {"status": "open"}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.encounter.refresh_from_db()
        self.assertEqual(self.encounter.status, "signed")

    def test_patch_signed_by_and_signed_at_ignored(self):
        """signed_at / signed_by are sign-managed and ignored on generic PATCH."""
        resp = self._client(self.medico_user).patch(
            self._detail_url(),
            {"signed_at": "2020-01-01T00:00:00Z", "signed_by": str(self.medico_user.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.encounter.refresh_from_db()
        self.assertIsNone(self.encounter.signed_at)
        self.assertIsNone(self.encounter.signed_by_id)

    def test_sign_action_still_works(self):
        """The dedicated sign action remains the legitimate path to status=signed."""
        resp = self._client(self.medico_user).post(f"/api/v1/encounters/{self.encounter.id}/sign/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.encounter.refresh_from_db()
        self.assertEqual(self.encounter.status, "signed")
        self.assertIsNotNone(self.encounter.signed_at)
        self.assertEqual(self.encounter.signed_by_id, self.medico_user.id)


class TestProtectTUSSCodeDeletionSignal(TenantTestCase):
    """The pre_delete signal must block hard-deleting a TUSSCode referenced by
    an EncounterProcedure in any tenant (cross-schema app-layer PROTECT)."""

    def setUp(self):
        self.medico_user, self.enf_user, self.patient, self.prof, self.encounter = _make_infra()
        self.tuss = _make_tuss(code="40304361")

    def test_delete_blocked_when_referenced_by_procedure(self):
        EncounterProcedure.objects.create(encounter=self.encounter, tuss_code=self.tuss)
        with self.assertRaises(ProtectedError) as ctx:
            self.tuss.delete()
        self.assertIn("EncounterProcedure", str(ctx.exception))
        self.assertTrue(TUSSCode.objects.filter(pk=self.tuss.pk).exists())

    def test_delete_allowed_when_not_referenced(self):
        unused = _make_tuss(code="40304370")
        unused.delete()
        self.assertFalse(TUSSCode.objects.filter(pk=unused.pk).exists())


class TestEncounterProcedureMultiTenantIsolation(TenantTestCase):
    """A procedure in tenant A must be invisible from tenant B.

    Following the project's tenant-test guidance: the 2nd schema is created/dropped
    from the public schema, and kept empty to avoid deferred-FK-trigger teardown
    failures. An empty B that returns zero procedures proves isolation — tenant A's
    rows never leak into B's schema.
    """

    def setUp(self):
        from apps.core.models import Tenant

        self.schema_a = self.__class__.tenant.schema_name
        # Provision tenant B (an empty schema) FIRST. Creating a Tenant runs DDL
        # (CREATE SCHEMA + migrate), which PostgreSQL refuses while the current
        # transaction has pending deferred-FK trigger events — exactly what
        # inserting tenant-A rows leaves behind. So create B before any A inserts,
        # and keep B empty so its DROP SCHEMA in tearDown stays clean.
        with schema_context(get_public_schema_name()):
            self.tenant_b = Tenant.objects.create(name="Clinic B EP", slug="clinicb-ep")
        self.medico_user, self.enf_user, self.patient, self.prof, self.encounter = _make_infra()
        self.tuss = _make_tuss(code="20104448")
        self.proc_a = EncounterProcedure.objects.create(
            encounter=self.encounter, tuss_code=self.tuss
        )

    def tearDown(self):
        # Dropping a tenant schema, like creating it, must run from the public
        # schema; FastTenantTestCase leaves the connection on fast_test.
        with schema_context(get_public_schema_name()):
            try:
                self.tenant_b.delete(force_drop=True)
            except Exception:
                self.tenant_b.delete()

    def test_procedure_isolated_to_tenant_a(self):
        with schema_context(self.schema_a):
            self.assertEqual(EncounterProcedure.objects.count(), 1)
        with schema_context(self.tenant_b.schema_name):
            self.assertEqual(EncounterProcedure.objects.count(), 0)
