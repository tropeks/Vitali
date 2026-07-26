"""S2 — gated + audited REST for the RH operacional resources."""

from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User
from apps.test_utils import TenantTestCase


class RHApiGatingTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.hr_role = Role.objects.create(name="rh", permissions=["hr.manage"])
        self.clinician_role = Role.objects.create(name="medico", permissions=["emr.read"])
        self.hr_user = User.objects.create_user(
            email="rh@clinic.test", password="pw", full_name="RH", role=self.hr_role
        )
        self.clinician = User.objects.create_user(
            email="doc@clinic.test", password="pw", full_name="Doc", role=self.clinician_role
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    def test_clinician_denied_positions(self):
        self.client.force_authenticate(user=self.clinician)
        assert self.client.get("/api/v1/hr/positions/").status_code == 403

    def test_hr_can_list_positions(self):
        self.client.force_authenticate(user=self.hr_user)
        assert self.client.get("/api/v1/hr/positions/").status_code == 200

    def test_position_create_is_audited(self):
        self.client.force_authenticate(user=self.hr_user)
        resp = self.client.post(
            "/api/v1/hr/positions/", {"title": "Recepcionista", "cbo": "4221-05"}, format="json"
        )
        assert resp.status_code == 201, resp.content
        assert AuditLog.objects.filter(
            action="position_created", resource_id=resp.json()["id"]
        ).exists()

    def test_duty_roster_create_is_audited(self):
        from apps.organization.models import Facility, LegalEntity

        entity = LegalEntity.objects.create(code="LE-API", name="E")
        facility = Facility.objects.create(code="FAC-API", name="F", legal_entity=entity)
        self.client.force_authenticate(user=self.hr_user)
        resp = self.client.post(
            "/api/v1/hr/duty-rosters/",
            {
                "facility": str(facility.id),
                "name": "Escala X",
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert AuditLog.objects.filter(
            action="duty_roster_created", resource_id=resp.json()["id"]
        ).exists()
