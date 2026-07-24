"""
E1-T4 — terminology search service + autocomplete API.

Service ranking + accent/case-insensitivity (unit) and the
GET /api/v1/terminology/<system>/?q= contract (200 authed / 401 anon / no write).
"""

from rest_framework.test import APIClient

from apps.core.models import CID10Code, Role, User
from apps.core.terminology import UnknownTerminologySystem, search
from apps.test_utils import TenantTestCase


def _seed_cid():
    colera = CID10Code.objects.create(code="A00", description="Cólera", category="A00-A09")
    CID10Code.objects.create(
        code="A000", description="Cólera devida a Vibrio cholerae", parent=colera
    )
    CID10Code.objects.create(code="E11", description="Diabetes mellitus tipo 2")
    CID10Code.objects.create(code="Z99", description="Inativo antigo", active=False)
    return colera


class TestTerminologySearchService(TenantTestCase):
    def setUp(self):
        _seed_cid()

    def test_exact_code_ranks_first(self):
        results = search("cid10", "A00")
        self.assertEqual(results[0]["code"], "A00")

    def test_code_prefix_matches(self):
        codes = [r["code"] for r in search("cid10", "A0")]
        self.assertIn("A00", codes)
        self.assertIn("A000", codes)

    def test_accent_insensitive_description(self):
        codes = [r["code"] for r in search("cid10", "colera")]
        self.assertIn("A00", codes)

    def test_case_insensitive_description(self):
        codes = [r["code"] for r in search("cid10", "COLERA")]
        self.assertIn("A00", codes)

    def test_substring_description(self):
        codes = [r["code"] for r in search("cid10", "mellitus")]
        self.assertIn("E11", codes)

    def test_exact_code_ranked_above_substring(self):
        # "A00" exact-code should rank before "A000" (code prefix).
        results = search("cid10", "A00")
        codes = [r["code"] for r in results]
        self.assertLess(codes.index("A00"), codes.index("A000"))

    def test_active_only(self):
        codes = [r["code"] for r in search("cid10", "Z99")]
        self.assertNotIn("Z99", codes)

    def test_hierarchy_context_returned(self):
        results = search("cid10", "A000")
        ctx = results[0]["context"]
        self.assertEqual(ctx["parent"]["code"], "A00")

    def test_empty_query_returns_empty(self):
        self.assertEqual(search("cid10", ""), [])
        self.assertEqual(search("cid10", "   "), [])

    def test_limit_respected(self):
        results = search("cid10", "A", limit=1)
        self.assertEqual(len(results), 1)

    def test_unknown_system_raises(self):
        with self.assertRaises(UnknownTerminologySystem):
            search("bogus", "x")


class TestTerminologySearchAPI(TenantTestCase):
    def setUp(self):
        _seed_cid()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        role = Role.objects.create(name="medico_term", permissions=["emr.read"])
        self.user = User.objects.create_user(
            email="term@clinic.test", full_name="Term User", password="TestPass123!", role=role
        )

    def _url(self, system="cid10", q="A00"):
        return f"/api/v1/terminology/{system}/?q={q}"

    def test_requires_authentication_401(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 401)

    def test_authenticated_returns_200_and_results(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["results"][0]["code"], "A00")
        self.assertEqual(data["system"], "cid10")

    def test_unknown_system_returns_404(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(self._url(system="bogus"))
        self.assertEqual(resp.status_code, 404)

    def test_write_method_not_allowed(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post("/api/v1/terminology/cid10/", {"code": "X"}, format="json")
        self.assertEqual(resp.status_code, 405)

    def test_empty_query_returns_empty_results(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.get("/api/v1/terminology/cid10/?q=")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])
