"""
Tests for LGPD compliance:
- CPF masking in MessageLog.content_preview
- ConversationSession deleted after booking
- Per-contact rate limiting
- Expired session cleanup task
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from apps.test_utils import TenantTestCase
from rest_framework.test import APIClient

from apps.whatsapp.models import ConversationSession, WhatsAppContact
from apps.whatsapp.views import _log_message, _check_rate_limit

import json
import hashlib
import hmac

WEBHOOK_URL = "/api/v1/whatsapp/webhook/"


def _make_contact(phone="5511900000099", opt_in=True):
    contact, _ = WhatsAppContact.objects.get_or_create(phone=phone)
    if opt_in and not contact.opt_in:
        contact.do_opt_in()
    return contact


class CPFRedactionAndSessionPurgeTests(TenantTestCase):

    def setUp(self):
        cache.clear()

    def test_messagelog_cpf_masked_in_content_preview(self):
        """CPF pattern in content must be masked before saving."""
        from apps.whatsapp.models import MessageLog
        contact = _make_contact()
        _log_message(contact, "inbound", "Meu CPF é 529.982.247-25 obrigado")
        log = MessageLog.objects.filter(contact=contact).first()
        self.assertIsNotNone(log)
        self.assertNotIn("529.982.247-25", log.content_preview)
        self.assertIn("***.***.***-**", log.content_preview)

    def test_messagelog_11digit_cpf_masked(self):
        from apps.whatsapp.models import MessageLog
        contact = _make_contact(phone="5511900000097")
        _log_message(contact, "inbound", "cpf 52998224725")
        log = MessageLog.objects.filter(contact=contact).first()
        self.assertNotIn("52998224725", log.content_preview)

    def test_cleanup_expired_sessions_task_deletes_old_sessions(self):
        from apps.whatsapp.tasks import cleanup_expired_sessions
        contact = _make_contact(phone="5511900000098")
        session, _ = ConversationSession.get_or_create_for_contact(contact)
        session.expires_at = timezone.now() - timedelta(minutes=31)
        session.save()

        cleanup_expired_sessions()

        self.assertFalse(ConversationSession.objects.filter(pk=session.pk).exists())

    def test_fresh_session_not_deleted_by_cleanup(self):
        from apps.whatsapp.tasks import cleanup_expired_sessions
        contact = _make_contact(phone="5511900000096")
        session, _ = ConversationSession.get_or_create_for_contact(contact)
        # expires_at is 30min from now — should NOT be deleted
        cleanup_expired_sessions()
        self.assertTrue(ConversationSession.objects.filter(pk=session.pk).exists())


class PerContactRateLimitTests(TenantTestCase):

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain

    def test_rate_limit_allows_first_20_messages(self):
        phone = "5511900000050"
        for i in range(20):
            self.assertTrue(_check_rate_limit(phone), f"Message {i+1} should be allowed")

    def test_21st_message_blocked(self):
        phone = "5511900000051"
        for _ in range(20):
            _check_rate_limit(phone)
        self.assertFalse(_check_rate_limit(phone))

    @override_settings(WHATSAPP_WEBHOOK_SECRET="")
    def test_rate_limited_webhook_still_returns_200(self):
        """Webhook always returns 200 even when rate limited."""
        phone = "5511900000052"
        # Exhaust rate limit
        for _ in range(21):
            cache_key = f"wa_rate:{phone}"
            cache.set(cache_key, 25, timeout=60)

        body = json.dumps({
            "event": "messages.upsert",
            "data": {"messages": [{
                "key": {"fromMe": False, "remoteJid": f"{phone}@s.whatsapp.net"},
                "message": {"conversation": "oi"},
            }]}
        }).encode()

        resp = self.client.post(WEBHOOK_URL, data=body, content_type="application/json")
        self.assertEqual(resp.status_code, 200)
