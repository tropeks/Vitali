"""
Tests for WhatsApp views — tenant routing, contacts, message logs.
"""
from unittest.mock import MagicMock, patch

from apps.test_utils import TenantTestCase
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.whatsapp.models import MessageLog, WhatsAppContact


def _make_user(role_name="admin"):
    role, _ = Role.objects.get_or_create(
        name=role_name,
        defaults={"permissions": ["whatsapp.read", "whatsapp.write"]},
    )
    return User.objects.create_user(
        email=f"wa_{role_name}_{id(role)}@test.com",
        password="pw",
        role=role,
    )


class WebhookTenantRoutingTests(TenantTestCase):
    """
    The webhook view must route to the correct tenant schema.
    django-tenants handles this via TenantMainMiddleware + SERVER_NAME.
    We verify the WhatsAppContact is created in THIS tenant's schema,
    not a different one's.
    """

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    @patch("apps.whatsapp.views.verify_webhook_signature", return_value=True)
    @patch("apps.whatsapp.views.ConversationFSM")
    @patch("apps.whatsapp.views.get_gateway")
    def test_webhook_creates_contact_in_tenant_schema(self, mock_gw, mock_fsm, mock_sig):
        mock_fsm.return_value.process.return_value = []
        mock_gw.return_value = MagicMock()
        import json
        body = json.dumps({
            "event": "messages.upsert",
            "data": {"messages": [{
                "key": {"fromMe": False, "remoteJid": "5511900000301@s.whatsapp.net"},
                "message": {"conversation": "oi"},
            }]}
        }).encode()
        resp = self.client.post(
            "/api/v1/whatsapp/webhook/",
            data=body,
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(WhatsAppContact.objects.filter(phone="5511900000301").exists())


class MessageLogViewSetTests(TenantTestCase):

    def setUp(self):
        FeatureFlag.objects.get_or_create(
            tenant=self.__class__.tenant,
            module_key="whatsapp",
            defaults={"is_enabled": True},
        )
        self.user = _make_user()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(user=self.user)

    def test_authenticated_user_can_list_message_logs(self):
        contact = WhatsAppContact.objects.create(phone="5511900000302")
        contact.do_opt_in()
        MessageLog.objects.create(
            contact=contact,
            direction="inbound",
            content_preview="Olá",
            message_type="text",
        )
        resp = self.client.get("/api/v1/whatsapp/message-logs/")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.data["count"], 1)

    def test_filter_by_phone(self):
        contact = WhatsAppContact.objects.create(phone="5511900000303")
        contact.do_opt_in()
        MessageLog.objects.create(contact=contact, direction="outbound", content_preview="Test", message_type="text")
        resp = self.client.get("/api/v1/whatsapp/message-logs/?phone=5511900000303")
        self.assertEqual(resp.status_code, 200)
        for item in resp.data["results"]:
            self.assertEqual(item["contact_phone"], "5511900000303")

    def test_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.get("/api/v1/whatsapp/message-logs/")
        self.assertIn(resp.status_code, [401, 403])


class WhatsAppContactViewSetTests(TenantTestCase):

    def setUp(self):
        FeatureFlag.objects.get_or_create(
            tenant=self.__class__.tenant,
            module_key="whatsapp",
            defaults={"is_enabled": True},
        )
        self.user = _make_user()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(user=self.user)

    def test_list_contacts(self):
        WhatsAppContact.objects.create(phone="5511900000304")
        resp = self.client.get("/api/v1/whatsapp/contacts/")
        self.assertEqual(resp.status_code, 200)

    def test_health_view_requires_auth(self):
        self.client.logout()
        resp = self.client.get("/api/v1/whatsapp/health/")
        self.assertIn(resp.status_code, [401, 403])
