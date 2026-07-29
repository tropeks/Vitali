"""RBAC gate for the (administrative) concession module.

Concession is administrative — assets/contracts/P&L — NOT clinical. A clinical
role such as ``enfermeiro`` must NOT reach it even when the tenant has the
``diagnostic_concession`` module active. Only the admin (carrying
``concession.read``/``concession.manage``) and Vitali platform operators pass.

Exercised through the ``material-unit-costs`` endpoint (a plain CRUD viewset);
the ``HasConcessionAccess`` gate is shared by all ~15 concession viewsets.
"""

from __future__ import annotations

from rest_framework.test import APIClient

from apps.concession.permissions import CONCESSION_MODULE_KEY
from apps.concession.tests.factories import make_material
from apps.core.models import FeatureFlag, Role, User
from apps.core.permissions import ADMIN_PERMISSIONS, NURSING_PERMISSIONS
from apps.test_utils import TenantTestCase

BASE = "/api/v1/concession"
LIST_URL = f"{BASE}/material-unit-costs/"


def _make_user(email, perms):
    role = Role.objects.create(name=f"role-{email}", permissions=perms)
    return User.objects.create_user(email=email, password="pw", role=role)


class ConcessionRbacTests(TenantTestCase):
    def setUp(self):
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key=CONCESSION_MODULE_KEY,
            defaults={"is_enabled": True},
        )
        self.material = make_material()

    def _client(self, user):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(user=user)
        return c

    # ── enfermeiro: denied on read AND write ──────────────────────────────────
    def test_nurse_get_list_forbidden(self):
        nurse = _make_user("nurse@test.local", NURSING_PERMISSIONS)
        resp = self._client(nurse).get(LIST_URL)
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_nurse_post_forbidden(self):
        nurse = _make_user("nurse2@test.local", NURSING_PERMISSIONS)
        resp = self._client(nurse).post(
            LIST_URL,
            {"material": str(self.material.pk), "unit_cost": "1.50"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    # ── admin: read AND write allowed ─────────────────────────────────────────
    def test_admin_get_list_allowed(self):
        admin = _make_user("admin@test.local", ADMIN_PERMISSIONS)
        resp = self._client(admin).get(LIST_URL)
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_admin_post_allowed(self):
        admin = _make_user("admin2@test.local", ADMIN_PERMISSIONS)
        resp = self._client(admin).post(
            LIST_URL,
            {"material": str(self.material.pk), "unit_cost": "1.50"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    # ── read-only capability: read yes, write no ──────────────────────────────
    def test_read_only_perm_can_get_but_not_post(self):
        reader = _make_user("reader@test.local", ["concession.read"])
        client = self._client(reader)
        self.assertEqual(client.get(LIST_URL).status_code, 200)
        resp = client.post(
            LIST_URL,
            {"material": str(self.material.pk), "unit_cost": "1.50"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content)

    # ── platform operator (Django superuser) bypasses ─────────────────────────
    def test_platform_admin_bypasses(self):
        superuser = User.objects.create_superuser(
            email="ops@vitali.local", password="pw", full_name="Ops"
        )
        resp = self._client(superuser).get(LIST_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
