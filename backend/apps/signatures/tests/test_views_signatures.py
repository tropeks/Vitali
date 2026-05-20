"""
Tests for the signatures REST endpoints. These exercise:
- The module/permission gate (FeatureFlag `signatures`)
- The per-user `signatures.sign` permission
- Successful signing round-trip via base64 payloads
- Listing + filtering of signatures
"""

from __future__ import annotations

import base64

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.signatures.models import DigitalSignature
from apps.signatures.tests.test_icp_brasil_signer import _make_self_signed_pkcs12
from apps.test_utils import TenantTestCase

SIGN_URL = "/api/v1/signatures/sign/"
LIST_URL = "/api/v1/signatures/"


def _make_user(*, role_name: str, perms: list[str]) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(email=f"{role_name}@test.com", password="pw", role=role)


class SignatureViewsTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="signatures",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(
            role_name="medico_sig",
            perms=["signatures.sign", "signatures.read", "patients.read"],
        )
        self.client.force_authenticate(user=self.user)

    def _payload(
        self,
        *,
        document: bytes = b"clinical doc",
        document_type: str = "encounter",
        document_id: str = "enc-1",
    ):
        pfx, _, _ = _make_self_signed_pkcs12(password="pw")
        return {
            "document_type": document_type,
            "document_id": document_id,
            "document_b64": base64.b64encode(document).decode("ascii"),
            "pkcs12_b64": base64.b64encode(pfx).decode("ascii"),
            "pkcs12_password": "pw",
        }

    # ─── Sign endpoint ────────────────────────────────────────────────────────

    def test_sign_creates_signature_row(self):
        resp = self.client.post(SIGN_URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["document_type"], "encounter")
        self.assertEqual(resp.data["document_id"], "enc-1")
        self.assertTrue(resp.data["signature_b64"])
        self.assertEqual(len(resp.data["document_hash_hex"]), 64)
        self.assertEqual(resp.data["signature_algorithm"], "SHA256withRSA")
        self.assertEqual(DigitalSignature.objects.count(), 1)

    def test_sign_returns_400_on_wrong_password(self):
        payload = self._payload()
        payload["pkcs12_password"] = "wrong"
        resp = self.client.post(SIGN_URL, payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.data)
        self.assertEqual(DigitalSignature.objects.count(), 0)

    def test_sign_returns_400_on_invalid_base64(self):
        payload = self._payload()
        payload["pkcs12_b64"] = "*** not base64 ***"
        resp = self.client.post(SIGN_URL, payload, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_sign_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="signatures").update(
            is_enabled=False
        )
        resp = self.client.post(SIGN_URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 403)

    def test_sign_blocked_without_signatures_sign_permission(self):
        reader = _make_user(role_name="reader_sig", perms=["signatures.read", "patients.read"])
        self.client.force_authenticate(user=reader)
        resp = self.client.post(SIGN_URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 403)

    def test_sign_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.post(SIGN_URL, self._payload(), format="json")
        self.assertIn(resp.status_code, [401, 403])

    def test_sign_validates_document_type(self):
        payload = self._payload(document_type="not_a_choice")
        resp = self.client.post(SIGN_URL, payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("document_type", resp.data)

    # ─── List endpoint ────────────────────────────────────────────────────────

    def test_list_returns_signatures_filtered_by_document(self):
        self.client.post(SIGN_URL, self._payload(document_id="enc-1"), format="json")
        self.client.post(SIGN_URL, self._payload(document_id="enc-2"), format="json")
        self.client.post(
            SIGN_URL,
            self._payload(document_type="prescription", document_id="rx-7"),
            format="json",
        )

        resp = self.client.get(LIST_URL, {"document_id": "enc-1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["document_id"], "enc-1")

        resp = self.client.get(LIST_URL, {"document_type": "prescription"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["document_type"], "prescription")

    def test_list_blocked_without_signatures_read_permission(self):
        no_perms = _make_user(role_name="no_sig", perms=["patients.read"])
        self.client.force_authenticate(user=no_perms)
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.status_code, 403)
