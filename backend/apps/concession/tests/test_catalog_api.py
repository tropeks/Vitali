"""B0-T1 — ConcessionService catalog CRUD (gated REST)."""

from __future__ import annotations

from rest_framework.test import APIClient

from apps.concession.models import ConcessionService
from apps.concession.tests.factories import make_user
from apps.core.models import AuditLog, FeatureFlag
from apps.test_utils import TenantTestCase

BASE = "/api/v1/concession"


class ConcessionServiceApiTests(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="diagnostic_concession",
            defaults={"is_enabled": True},
        )
        self.user = make_user()
        self.client.force_authenticate(user=self.user)

    def test_create_service_201_and_audited(self):
        resp = self.client.post(
            f"{BASE}/services/",
            {"code": "RX", "name": "Raio-X", "modality": "RX", "tuss_code": "40901220"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(ConcessionService.objects.filter(code="RX").count(), 1)
        self.assertTrue(
            AuditLog.objects.filter(resource_type="ConcessionService", action="create").exists()
        )

    def test_list_services_200(self):
        ConcessionService.objects.create(code="US", name="Ultrassom")
        resp = self.client.get(f"{BASE}/services/")
        self.assertEqual(resp.status_code, 200, resp.content)
        results = resp.data["results"] if isinstance(resp.data, dict) else resp.data
        self.assertEqual(len(results), 1)

    def test_update_service_200(self):
        svc = ConcessionService.objects.create(code="TC", name="Tomografia")
        resp = self.client.patch(f"{BASE}/services/{svc.pk}/", {"active": False}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        svc.refresh_from_db()
        self.assertFalse(svc.active)

    def test_delete_service_204(self):
        svc = ConcessionService.objects.create(code="RM", name="Ressonância")
        resp = self.client.delete(f"{BASE}/services/{svc.pk}/")
        self.assertEqual(resp.status_code, 204, resp.content)
        self.assertFalse(ConcessionService.objects.filter(pk=svc.pk).exists())

    def test_tier_gate_403_without_feature_flag(self):
        FeatureFlag.objects.filter(
            tenant=self.__class__.tenant, module_key="diagnostic_concession"
        ).update(is_enabled=False)
        self.assertEqual(self.client.get(f"{BASE}/services/").status_code, 403)
