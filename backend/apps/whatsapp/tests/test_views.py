"""
Tests for WhatsApp views — tenant routing, contacts, message logs.
"""

from unittest.mock import MagicMock, patch

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.test_utils import TenantTestCase
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

        body = json.dumps(
            {
                "event": "messages.upsert",
                "data": {
                    "messages": [
                        {
                            "key": {"fromMe": False, "remoteJid": "5511900000301@s.whatsapp.net"},
                            "message": {"conversation": "oi"},
                        }
                    ]
                },
            }
        ).encode()
        resp = self.client.post(
            "/api/v1/whatsapp/webhook/",
            data=body,
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(WhatsAppContact.objects.filter(phone="5511900000301").exists())


class WebhookIdempotencyTests(TenantTestCase):
    """Webhook redeliveries (same Evolution msg.key.id) must be processed once."""

    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    def _post(self, message_id, text="oi", phone="5511900000401"):
        import json

        body = json.dumps(
            {
                "event": "messages.upsert",
                "data": {
                    "messages": [
                        {
                            "key": {
                                "fromMe": False,
                                "remoteJid": f"{phone}@s.whatsapp.net",
                                "id": message_id,
                            },
                            "message": {"conversation": text},
                        }
                    ]
                },
            }
        ).encode()
        return self.client.post(
            "/api/v1/whatsapp/webhook/", data=body, content_type="application/json"
        )

    @patch("apps.whatsapp.views.verify_webhook_signature", return_value=True)
    @patch("apps.whatsapp.views.get_gateway")
    def test_redelivered_message_id_is_processed_once(self, mock_gw, mock_sig):
        gateway = MagicMock()
        mock_gw.return_value = gateway
        resp1 = self._post("EVOMSG-1")
        resp2 = self._post("EVOMSG-1")  # redelivery — same id
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        # Only one inbound log and one outbound prompt — duplicate ignored silently.
        self.assertEqual(MessageLog.objects.filter(direction="inbound").count(), 1)
        self.assertEqual(gateway.send_text.call_count, 1)

    @patch("apps.whatsapp.views.verify_webhook_signature", return_value=True)
    @patch("apps.whatsapp.views.get_gateway")
    def test_distinct_message_ids_are_both_processed(self, mock_gw, mock_sig):
        mock_gw.return_value = MagicMock()
        self._post("EVOMSG-A")
        self._post("EVOMSG-B", text="ajuda")
        self.assertEqual(MessageLog.objects.filter(direction="inbound").count(), 2)

    @patch("apps.whatsapp.views.get_gateway")
    def test_duplicate_triage_answer_does_not_shift_red_flag_answers(self, mock_gw):
        """Clinical safety: a redelivered 'sim' must not be consumed as the
        answer to the NEXT red-flag question (that would displace every
        subsequent answer, masking or fabricating red flags)."""
        from django.apps import apps as django_apps

        from apps.whatsapp.views import WebhookView

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="triage", defaults={"is_enabled": True}
        )
        mock_gw.return_value = MagicMock()
        phone = "5511900000402"
        contact = WhatsAppContact.objects.create(phone=phone)
        contact.do_opt_in()

        view = WebhookView()
        view._process_message(phone, "triagem", "text", "TRG-1")
        view._process_message(phone, "estou com dor de cabeça", "text", "TRG-2")
        view._process_message(phone, "sim", "text", "TRG-3")
        view._process_message(phone, "sim", "text", "TRG-3")  # redelivery

        TriageSession = django_apps.get_model("triage", "TriageSession")
        ts = TriageSession.objects.get()
        # Exactly ONE red-flag question answered — the duplicate was dropped.
        self.assertEqual(len(ts.answers), 1)


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
        MessageLog.objects.create(
            contact=contact, direction="outbound", content_preview="Test", message_type="text"
        )
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
