"""
Tests for ConversationFSM — state transitions, intent detection, slot reservation.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone

from apps.core.models import AuditLog, FeatureFlag
from apps.test_utils import TenantTestCase
from apps.triage.models import TriageSession
from apps.whatsapp.context import get_context, set_context
from apps.whatsapp.fsm import ConversationFSM, _is_valid_cpf, detect_intent
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
        with patch.object(
            fsm, "_get_specialties", return_value=[{"id": 1, "name": "Clínica Geral"}]
        ):
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


def _enable_triage(tenant, enabled=True):
    FeatureFlag.objects.update_or_create(
        tenant=tenant, module_key="triage", defaults={"is_enabled": enabled}
    )


def _answer_all_questions(fsm, session, answers):
    """Walk TRIAGE_QUESTIONS feeding the given ordered yes/no answers."""
    out = []
    for ans in answers:
        out = fsm.process(ans)
        session.refresh_from_db()
    return out


class TriageFlowTests(TenantTestCase):
    """End-to-end triage sub-flow over the WhatsApp ConversationFSM."""

    # Ordered to leave the patient conscious (altered_consciousness #4 → "sim")
    # and every red flag negative → routine classification.
    ROUTINE_ANSWERS = ["nao", "nao", "nao", "sim", "nao", "nao"]

    def setUp(self):
        _enable_triage(self.tenant)

    def test_triagem_gated_off_when_flag_disabled(self):
        _enable_triage(self.tenant, enabled=False)
        contact = _make_contact()
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        msgs = fsm.process("triagem")
        session.refresh_from_db()
        self.assertEqual(session.state, "IDLE")
        self.assertIn("não está disponível", msgs[0])
        self.assertEqual(TriageSession.objects.count(), 0)

    def test_triagem_intent_starts_session(self):
        contact = _make_contact()
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        msgs = fsm.process("triagem")
        session.refresh_from_db()
        self.assertEqual(session.state, "TRIAGE_COMPLAINT")
        self.assertEqual(TriageSession.objects.count(), 1)
        ts = TriageSession.objects.get()
        self.assertEqual(get_context(session)["triage_session_id"], str(ts.id))
        self.assertEqual(ts.contact_phone, contact.phone)
        self.assertIn("descreva", msgs[0].lower())

    def test_complaint_advances_to_questions(self):
        contact = _make_contact()
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        fsm.process("triagem")
        msgs = fsm.process("dor de garganta há dois dias")
        session.refresh_from_db()
        self.assertEqual(session.state, "TRIAGE_QUESTIONS")
        ts = TriageSession.objects.get()
        self.assertEqual(ts.chief_complaint, "dor de garganta há dois dias")
        # First red-flag question is sent
        self.assertIn("sim", msgs[0].lower())

    def test_full_flow_routine_classification(self):
        contact = _make_contact()
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        fsm.process("triagem")
        fsm.process("dor de garganta leve")
        msgs = _answer_all_questions(fsm, session, self.ROUTINE_ANSWERS)

        ts = TriageSession.objects.get()
        self.assertEqual(ts.urgency, "routine")
        self.assertEqual(ts.status, TriageSession.STATUS_EVALUATED)
        # Conversation returns to IDLE and clears the triage handle
        self.assertEqual(session.state, "IDLE")
        self.assertIsNone(get_context(session)["triage_session_id"])
        self.assertIn("urgência", msgs[0].lower())

    def test_unparseable_answer_reprompts(self):
        contact = _make_contact()
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        fsm.process("triagem")
        fsm.process("dor de garganta")
        msgs = fsm.process("talvez, não sei")
        session.refresh_from_db()
        self.assertEqual(session.state, "TRIAGE_QUESTIONS")
        self.assertIn("sim", msgs[0].lower())

    def test_emergency_keyword_notifies_staff(self):
        from apps.emr.models import EscalationConfig

        EscalationConfig.objects.create(is_active=True, notify_emails=["enfermagem@clinica.test"])
        contact = _make_contact()
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        fsm.process("triagem")
        # "dor no peito" is an emergency chief-complaint keyword → emergency
        # regardless of the red-flag answers.
        fsm.process("estou com dor no peito")
        # patch must stay active while captureOnCommitCallbacks executes the
        # on_commit callback, so the patch wraps the capture (not vice-versa).
        with patch("apps.triage.tasks.send_triage_emergency_notification.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                msgs = _answer_all_questions(fsm, session, self.ROUTINE_ANSWERS)

        ts = TriageSession.objects.get()
        self.assertEqual(ts.urgency, "emergency")
        self.assertEqual(ts.status, TriageSession.STATUS_ESCALATED)

        audit = AuditLog.objects.filter(action="triage_emergency_escalated").get()
        self.assertEqual(audit.resource_id, str(ts.id))
        self.assertEqual(audit.new_data["notify_emails"], ["enfermagem@clinica.test"])

        # Staff delivery enqueued on commit with the configured recipients
        self.assertEqual(len(callbacks), 1)
        delay.assert_called_once_with(str(ts.id), ["enfermagem@clinica.test"])
        self.assertIn("emergência", msgs[0].lower())

    def test_emergency_without_recipients_still_audits_and_is_safe(self):
        contact = _make_contact()
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        fsm.process("triagem")
        fsm.process("tive um desmaio")  # emergency keyword
        msgs = _answer_all_questions(fsm, session, self.ROUTINE_ANSWERS)

        ts = TriageSession.objects.get()
        self.assertEqual(ts.urgency, "emergency")
        self.assertTrue(AuditLog.objects.filter(action="triage_emergency_escalated").exists())
        self.assertIn("emergência", msgs[0].lower())

    def test_sair_during_triage_questions_opts_out(self):
        contact = _make_contact()
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        fsm.process("triagem")
        fsm.process("dor de garganta")
        fsm.process("sair")
        session.refresh_from_db()
        self.assertEqual(session.state, "OPTED_OUT")

    def test_bare_nao_during_triage_is_a_clinical_answer(self):
        contact = _make_contact()
        session = _make_session(contact, state="IDLE")
        fsm, _ = _make_fsm(session)
        fsm.process("triagem")
        fsm.process("dor de garganta")
        fsm.process("nao")  # answers chest_pain, does NOT opt out
        session.refresh_from_db()
        self.assertEqual(session.state, "TRIAGE_QUESTIONS")
        ts = TriageSession.objects.get()
        self.assertEqual(ts.answers.get("chest_pain"), "não")


class ConversationSessionLockingTests(TenantTestCase):
    """
    Verify that select_for_update() is used in process() to prevent concurrent
    double-tap corruption. Uses TransactionTestCase for threading.
    """

    def test_select_for_update_called_in_process_message(self):
        """WebhookView._process_message must lock the session row."""
        import inspect

        from apps.whatsapp.views import WebhookView

        source = inspect.getsource(WebhookView._process_message)
        self.assertIn("select_for_update", source)
