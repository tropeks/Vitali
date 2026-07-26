"""S-IA2 — Escala setorial: roster.manage permission + object-level unit scope.

Escala/plantão is a SECTOR-SUPERVISOR function (docs/UI_NAVIGATION_IA.md §3,
CANONICAL_FEATURE_MAP.md §E), not central RH. These lock in:

Task A — DutyRoster / RosterSlot viewsets authorize off ``RosterAccessPermission``:
  admin capability OR central ``hr.manage`` (transition) OR sector ``roster.manage``;
  a role with none of those is 403. Never keyed off role.name (A01).

Task B — a non-admin ``roster.manage`` supervisor is scoped to the
  OrganizationalUnit(s) of their active EmployeeAssignment: they see rosters for
  THEIR unit/facility, not the whole tenant.
"""

from datetime import date, time

from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.hr.models import DutyRoster, Employee, EmployeeAssignment, RosterSlot
from apps.organization.models import Facility, LegalEntity, OrganizationalUnit
from apps.test_utils import TenantTestCase

DUTY = "/api/v1/hr/duty-rosters/"
SLOTS = "/api/v1/hr/roster-slots/"


def _facility(code):
    entity = LegalEntity.objects.create(code=f"LE-{code}", name=f"Entidade {code}")
    return Facility.objects.create(code=f"FAC-{code}", name=f"Clínica {code}", legal_entity=entity)


def _unit(facility, code):
    return OrganizationalUnit.objects.create(code=code, name=f"Setor {code}", facility=facility)


def _roster(facility, name):
    return DutyRoster.objects.create(
        facility=facility, name=name, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
    )


class RosterAccessPermissionTests(TenantTestCase):
    """Task A — permission gating (no role.name)."""

    def setUp(self):
        super().setUp()
        self.facility = _facility("A")
        self.roster = _roster(self.facility, "Escala PS")

        self.admin_role = Role.objects.create(name="admin", permissions=["admin"], is_system=True)
        self.roster_role = Role.objects.create(name="enf-chefe", permissions=["roster.manage"])
        self.hr_role = Role.objects.create(name="rh", permissions=["hr.manage"])
        self.clinician_role = Role.objects.create(name="medico", permissions=["emr.read"])
        # A role merely NAMED admin but with no admin capability must NOT pass.
        self.forged_role = Role.objects.create(name="admin", permissions=["emr.read"])

        def _user(email, role):
            return User.objects.create_user(
                email=email, password="TestPass123!", full_name=email, role=role
            )

        self.admin = _user("adm@t.test", self.admin_role)
        self.supervisor = _user("sup@t.test", self.roster_role)
        self.hr = _user("hr@t.test", self.hr_role)
        self.clinician = _user("doc@t.test", self.clinician_role)
        self.forged = _user("forged@t.test", self.forged_role)

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    def _create_payload(self):
        return {
            "facility": str(self.facility.id),
            "name": "Nova escala",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
        }

    def test_roster_manage_can_list(self):
        self.client.force_authenticate(user=self.supervisor)
        self.assertEqual(self.client.get(DUTY).status_code, 200)

    def test_roster_manage_can_create(self):
        self.client.force_authenticate(user=self.supervisor)
        resp = self.client.post(DUTY, self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 201)

    def test_hr_manage_still_allowed_transition(self):
        self.client.force_authenticate(user=self.hr)
        self.assertEqual(self.client.get(DUTY).status_code, 200)

    def test_admin_allowed(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.get(DUTY).status_code, 200)

    def test_no_perm_denied_list(self):
        self.client.force_authenticate(user=self.clinician)
        self.assertEqual(self.client.get(DUTY).status_code, 403)

    def test_no_perm_denied_create(self):
        self.client.force_authenticate(user=self.clinician)
        resp = self.client.post(DUTY, self._create_payload(), format="json")
        self.assertEqual(resp.status_code, 403)

    def test_forged_admin_name_denied(self):
        self.client.force_authenticate(user=self.forged)
        self.assertEqual(self.client.get(DUTY).status_code, 403)

    def test_slots_endpoint_gated_same_way(self):
        self.client.force_authenticate(user=self.clinician)
        self.assertEqual(self.client.get(SLOTS).status_code, 403)
        self.client.force_authenticate(user=self.supervisor)
        self.assertEqual(self.client.get(SLOTS).status_code, 200)


class RosterUnitScopeTests(TenantTestCase):
    """Task B — object-level unit scope for non-admin roster.manage users."""

    def setUp(self):
        super().setUp()
        self.fac_a = _facility("SA")
        self.fac_b = _facility("SB")
        self.unit_a = _unit(self.fac_a, "UA")
        self.unit_b = _unit(self.fac_b, "UB")
        self.roster_a = _roster(self.fac_a, "Escala A")
        self.roster_b = _roster(self.fac_b, "Escala B")

        self.roster_role = Role.objects.create(name="enf-chefe", permissions=["roster.manage"])
        self.admin_role = Role.objects.create(name="admin", permissions=["admin"], is_system=True)

        sup_user = User.objects.create_user(
            email="sup-scope@t.test",
            password="TestPass123!",
            full_name="Sup",
            role=self.roster_role,
        )
        self.supervisor = sup_user
        # Link supervisor -> Employee -> active assignment on unit_a.
        self.sup_employee = Employee.objects.create(
            user=sup_user,
            hire_date=date(2026, 1, 1),
            contract_type="clt",
            employment_status="active",
        )
        EmployeeAssignment.objects.create(
            employee=self.sup_employee, unit=self.unit_a, start_date=date(2026, 1, 1), active=True
        )
        self.admin = User.objects.create_user(
            email="adm-scope@t.test", password="TestPass123!", full_name="Adm", role=self.admin_role
        )

        emp2_user = User.objects.create_user(
            email="w2@t.test", password="TestPass123!", full_name="W2"
        )
        emp2 = Employee.objects.create(
            user=emp2_user,
            hire_date=date(2026, 1, 1),
            contract_type="clt",
            employment_status="active",
        )
        self.slot_a = RosterSlot.objects.create(
            roster=self.roster_a,
            employee=self.sup_employee,
            unit=self.unit_a,
            date=date(2026, 8, 10),
            start_time=time(7, 0),
            end_time=time(13, 0),
        )
        self.slot_b = RosterSlot.objects.create(
            roster=self.roster_b,
            employee=emp2,
            unit=self.unit_b,
            date=date(2026, 8, 10),
            start_time=time(7, 0),
            end_time=time(13, 0),
        )

        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    def _ids(self, resp):
        data = resp.json()
        results = data["results"] if isinstance(data, dict) and "results" in data else data
        return {row["id"] for row in results}

    def test_supervisor_sees_only_own_facility_rosters(self):
        self.client.force_authenticate(user=self.supervisor)
        ids = self._ids(self.client.get(DUTY))
        self.assertIn(str(self.roster_a.id), ids)
        self.assertNotIn(str(self.roster_b.id), ids)

    def test_supervisor_sees_only_own_unit_slots(self):
        self.client.force_authenticate(user=self.supervisor)
        ids = self._ids(self.client.get(SLOTS))
        self.assertIn(str(self.slot_a.id), ids)
        self.assertNotIn(str(self.slot_b.id), ids)

    def test_supervisor_cannot_retrieve_foreign_roster(self):
        self.client.force_authenticate(user=self.supervisor)
        resp = self.client.get(f"{DUTY}{self.roster_b.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_admin_sees_all_rosters(self):
        self.client.force_authenticate(user=self.admin)
        ids = self._ids(self.client.get(DUTY))
        self.assertIn(str(self.roster_a.id), ids)
        self.assertIn(str(self.roster_b.id), ids)
