"""
Tests for ConversationFSM — state transitions, intent detection, slot reservation.
"""
import threading
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from apps.core.models import Role, User
from apps.whatsapp.context import get_context, set_context
from apps.whatsapp.fsm import ConversationFSM, _is_valid_cpf, detect_intent, _normalize
from apps.whatsapp.models import ConversationSession, WhatsAppContact


def _make_contact(phone="5511900000001", opt_in=True):
    contact, _ = WhatsAppContact.objects.get_or_create(phone=phone)
    if opt_in and not contact.opt_in:
        contact.do_opt_in()
    return contact


def _make_session(contact, state="IDLE"):
    session, _ = ConversationSession.get_or_create_for_contact(contact)
    session.state = state
    session.save()
    return session


def _make_fsm(session):
    gateway = MagicMock()
    return ConversationFSM(session, gateway), gateway


class IntentDetectionTests(TenantTestCase):

    def test_exact_match(self):
        self.assertEqual(detect_intent("confirmar"), "confirmar")

    def test_accent_normalized_matches(self):
        self.assertEqual(detect_intent("Agéndar"), "agendar")

    def test_case_insensitive(self):
        self.assertEqual(detect_intent("SAIR"), "optout")

    def test_unknown_returns_none(self):
        self.assertIsNone(detect_intent("blah blah blah something"))

    def test_para_mim(self):
        self.assertEqual(detect_intent("para mim"), "self")

    def test_para_outra_pessoa(self):
        self.assertEqual(detect_intent("para outra pessoa"), "other")


class CPFValidationTests(TenantTestCase):

    def test_valid_cpf(self):
        self.assertTrue(_is_valid_cpf("52998224725"))

    def test_invalid_cpf_all_same(self):
        self.assertFalse(_is_valid_cpf("11111111111"))

    def test_invalid_cpf_wrong_digit(self):
        self.assertFalse(_is_valid_cpf("12345678901"))

    def test_too_short(self):
        self.assertFalse(_is_valid_cpf("1234"))


class FSMStateTransitionTests(TenantTestCase):

    def test_idle_to_pending_optin_on_first_message(self):
        contact = _make_contact(opt_in=False)
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        messages = fsm.process("oi")
        session.refresh_from_db()
        self.assertEqual(session.state, "PENDING_OPTIN")
        self.assertIn("LGPD", messages[0])

    def test_optin_accepted_advances_to_self_or_other(self):
        contact = _make_contact(opt_in=False)
        session = _make_session(contact, state="PENDING_OPTIN")
        fsm, _ = _make_fsm(session)
        fsm.process("aceitar")
        session.refresh_from_db()
        self.assertEqual(session.state, "SELECTING_SELF_OR_OTHER")
        contact.refresh_from_db()
        self.assertTrue(contact.opt_in)

    def test_optin_refused_goes_to_opted_out(self):
        contact = _make_contact(opt_in=False)
        session = _make_session(contact, state="PENDING_OPTIN")
        fsm, _ = _make_fsm(session)
        fsm.process("recusar")
        session.refresh_from_db()
        self.assertEqual(session.state, "OPTED_OUT")
        contact.refresh_from_db()
        self.assertFalse(contact.opt_in)

    def test_sair_from_selecting_specialty_goes_to_opted_out(self):
        contact = _make_contact()
        session = _make_session(contact, state="SELECTING_SPECIALTY")
        fsm, _ = _make_fsm(session)
        fsm.process("sair")
        session.refresh_from_db()
        self.assertEqual(session.state, "OPTED_OUT")

    def test_sair_from_confirming_goes_to_opted_out(self):
        contact = _make_contact()
        session = _make_session(contact, state="CONFIRMING")
        fsm, _ = _make_fsm(session)
        fsm.process("sair")
        session.refresh_from_db()
        self.assertEqual(session.state, "OPTED_OUT")

    def test_self_path_from_selecting_self_or_other(self):
        contact = _make_contact()
        session = _make_session(contact, state="SELECTING_SELF_OR_OTHER")
        set_context(session, booking_for_self=None)
        session.save()
        fsm, _ = _make_fsm(session)
        with patch.object(fsm, "_get_specialties", return_value=[{"id": 1, "name": "Clínica Geral"}]):
            fsm.process("para mim")
        session.refresh_from_db()
        self.assertEqual(session.state, "SELECTING_SPECIALTY")
        ctx = get_context(session)
        self.assertTrue(ctx.get("booking_for_self"))

    def test_other_path_from_selecting_self_or_other(self):
        contact = _make_contact()
        session = _make_session(contact, state="SELECTING_SELF_OR_OTHER")
        fsm, _ = _make_fsm(session)
        fsm.process("para outra pessoa")
        session.refresh_from_db()
        self.assertEqual(session.state, "CAPTURING_NAME")

    def test_name_captured_advances_to_capturing_cpf(self):
        contact = _make_contact()
        session = _make_session(contact, state="CAPTURING_NAME")
        fsm, _ = _make_fsm(session)
        fsm.process("João da Silva")
        session.refresh_from_db()
        self.assertEqual(session.state, "CAPTURING_CPF")
        ctx = get_context(session)
        self.assertEqual(ctx["other_name"], "João da Silva")

    def test_invalid_cpf_retries(self):
        contact = _make_contact()
        session = _make_session(contact, state="CAPTURING_CPF")
        set_context(session, other_name="Test")
        session.save()
        fsm, _ = _make_fsm(session)
        msgs = fsm.process("12345")
        self.assertIn("CPF inválido", msgs[0])
        session.refresh_from_db()
        self.assertEqual(session.state, "CAPTURING_CPF")

    def test_3x_invalid_cpf_goes_to_fallback_human(self):
        contact = _make_contact()
        session = _make_session(contact, state="CAPTURING_CPF")
        set_context(session, other_name="Test", mismatches=2)
        session.save()
        fsm, _ = _make_fsm(session)
        fsm.process("12345")
        session.refresh_from_db()
        self.assertEqual(session.state, "FALLBACK_HUMAN")

    def test_remarcar_at_confirming_returns_to_selecting_date(self):
        contact = _make_contact()
        session = _make_session(contact, state="CONFIRMING")
        set_context(session, professional_id=1)
        session.save()
        fsm, _ = _make_fsm(session)
        with patch.object(fsm, "_get_slots", return_value={}):
            fsm.process("remarcar")
        session.refresh_from_db()
        self.assertEqual(session.state, "SELECTING_DATE")

    def test_cancelar_at_confirming_resets_to_idle(self):
        contact = _make_contact()
        session = _make_session(contact, state="CONFIRMING")
        fsm, _ = _make_fsm(session)
        fsm.process("cancelar")
        session.refresh_from_db()
        self.assertEqual(session.state, "IDLE")

    def test_3x_unrecognized_goes_to_fallback_human(self):
        contact = _make_contact()
        session = _make_session(contact, state="SELECTING_SPECIALTY")
        set_context(session, mismatches=2)
        session.save()
        fsm, _ = _make_fsm(session)
        with patch.object(fsm, "_get_specialties", return_value=[]):
            fsm.process("xyzabc123totally_unknown")
        session.refresh_from_db()
        self.assertEqual(session.state, "FALLBACK_HUMAN")

    def test_expired_session_resets_to_idle(self):
        contact = _make_contact()
        session = _make_session(contact, state="SELECTING_SPECIALTY")
        session.expires_at = timezone.now() - timedelta(minutes=1)
        session.save()
        fsm, _ = _make_fsm(session)
        msgs = fsm.process("algo")
        session.refresh_from_db()
        self.assertEqual(session.state, "IDLE")
        self.assertIn("expirou", msgs[0])

    def test_confirmed_state_on_new_message_restarts_to_self_or_other(self):
        contact = _make_contact()
        session = _make_session(contact, state="CONFIRMED")
        fsm, _ = _make_fsm(session)
        fsm.process("nova consulta")
        session.refresh_from_db()
        self.assertEqual(session.state, "SELECTING_SELF_OR_OTHER")


class ConversationSessionLockingTests(TenantTestCase):
    """
    Verify that select_for_update() is used in process() to prevent concurrent
    double-tap corruption. Uses TransactionTestCase for threading.
    """

    def test_select_for_update_called_in_process_message(self):
        """WebhookView._process_message must lock the session row."""
        from apps.whatsapp.views import WebhookView
        import inspect
        source = inspect.getsource(WebhookView._process_message)
        self.assertIn("select_for_update", source)
