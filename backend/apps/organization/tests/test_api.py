from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.test_utils import TenantTestCase

from ..models import Facility, LegalEntity


class OrganizationAPITests(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.role = Role.objects.create(name="organizational-manager", permissions=[])
        self.user = User.objects.create_user(
            email="organization@test.com",
            password="TestPass123!",
            full_name="Organization Manager",
            role=self.role,
        )
        self.client.force_authenticate(self.user)

    def grant(self, *permissions):
        self.role.permissions = list(permissions)
        self.role.save(update_fields=["permissions"])
        self.user.refresh_from_db()

    def test_read_permission_does_not_allow_writes(self):
        self.grant("organization.read")

        self.assertEqual(self.client.get("/api/v1/organization/legal-entities/").status_code, 200)
        response = self.client.post(
            "/api/v1/organization/legal-entities/",
            {"code": "LE-01", "name": "Hospital Vitali"},
        )

        self.assertEqual(response.status_code, 403)

    def test_write_permission_creates_complete_hierarchy(self):
        self.grant("organization.write")
        legal_entity = self.client.post(
            "/api/v1/organization/legal-entities/",
            {"code": "LE-01", "name": "Grupo Vitali", "legal_name": "Grupo Vitali S.A."},
        )
        self.assertEqual(legal_entity.status_code, 201)

        facility = self.client.post(
            "/api/v1/organization/facilities/",
            {
                "code": "HOSP-01",
                "name": "Hospital Central",
                "legal_entity": legal_entity.data["id"],
            },
        )
        self.assertEqual(facility.status_code, 201)

        unit = self.client.post(
            "/api/v1/organization/units/",
            {"code": "UTI-01", "name": "UTI Adulto", "facility": facility.data["id"]},
        )
        self.assertEqual(unit.status_code, 201)

        cost_center = self.client.post(
            "/api/v1/organization/cost-centers/",
            {
                "code": "CC-UTI-01",
                "name": "Centro de custo UTI",
                "legal_entity": legal_entity.data["id"],
                "facility": facility.data["id"],
            },
        )
        self.assertEqual(cost_center.status_code, 201)

    def test_rejects_cross_facility_unit_parent(self):
        self.grant("organization.write")
        entity = LegalEntity.objects.create(code="LE-01", name="Grupo")
        first = Facility.objects.create(code="F-01", name="Hospital A", legal_entity=entity)
        second = Facility.objects.create(code="F-02", name="Hospital B", legal_entity=entity)
        parent = self.client.post(
            "/api/v1/organization/units/",
            {"code": "U-01", "name": "Unidade A", "facility": str(first.id)},
        )

        response = self.client.post(
            "/api/v1/organization/units/",
            {
                "code": "U-02",
                "name": "Unidade B",
                "facility": str(second.id),
                "parent": parent.data["id"],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("parent", response.data)

    def test_delete_requires_separate_permission(self):
        entity = LegalEntity.objects.create(code="LE-01", name="Grupo")
        self.grant("organization.write")
        denied = self.client.delete(f"/api/v1/organization/legal-entities/{entity.id}/")
        self.assertEqual(denied.status_code, 403)

        self.grant("organization.delete")
        allowed = self.client.delete(f"/api/v1/organization/legal-entities/{entity.id}/")
        self.assertEqual(allowed.status_code, 204)
