"""Tests for the Triagem Inteligente FSM primitive."""

from __future__ import annotations

from rest_framework.test import APIClient

from apps.core.models import FeatureFlag, Role, User
from apps.test_utils import TenantTestCase
from apps.triage.models import TriageSession
from apps.triage.services.evaluator import (
    URGENCY_EMERGENCY,
    URGENCY_ROUTINE,
    URGENCY_URGENT,
    evaluate,
)
from apps.triage.services.question_bank import RED_FLAG_QUESTIONS, question_keys

QUESTIONS_URL = "/api/v1/triage/questions/"
SESSIONS_URL = "/api/v1/triage/sessions/"


def _detail(pk):
    return f"/api/v1/triage/sessions/{pk}/"


def _complaint(pk):
    return f"/api/v1/triage/sessions/{pk}/complaint/"


def _answer(pk):
    return f"/api/v1/triage/sessions/{pk}/answer/"


def _evaluate(pk):
    return f"/api/v1/triage/sessions/{pk}/evaluate/"


def _complete(pk):
    return f"/api/v1/triage/sessions/{pk}/complete/"


def _cancel(pk):
    return f"/api/v1/triage/sessions/{pk}/cancel/"


def _make_user(*, role_name: str, perms: list[str]) -> User:
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": perms})
    role.permissions = perms
    role.save()
    return User.objects.create_user(
        email=f"{role_name}@test.com", password="pw", role=role, full_name="Test"
    )


# ─── Evaluator unit tests ─────────────────────────────────────────────────────


class TriageEvaluatorTest(TenantTestCase):
    def _all_no(self) -> dict[str, str]:
        # Default "não" except `altered_consciousness` which gets "sim" (i.e.
        # patient IS oriented → not a red flag).
        return {
            q.key: ("sim" if q.key == "altered_consciousness" else "não")
            for q in RED_FLAG_QUESTIONS
        }

    def test_routine_when_no_red_flags_and_neutral_complaint(self):
        decision = evaluate("Dor de cabeça leve há 2 dias.", self._all_no())
        self.assertEqual(decision.urgency, URGENCY_ROUTINE)
        self.assertEqual(decision.red_flags_positive, 0)

    def test_emergency_keyword_in_complaint(self):
        decision = evaluate("Acho que estou tendo um infarto.", self._all_no())
        self.assertEqual(decision.urgency, URGENCY_EMERGENCY)

    def test_severe_bleeding_alone_triggers_emergency(self):
        answers = self._all_no()
        answers["severe_bleeding"] = "sim"
        decision = evaluate("Cortei o braço.", answers)
        self.assertEqual(decision.urgency, URGENCY_EMERGENCY)

    def test_altered_consciousness_no_triggers_emergency(self):
        answers = self._all_no()
        answers["altered_consciousness"] = "não"  # patient is NOT oriented
        decision = evaluate("Estou tonto.", answers)
        self.assertEqual(decision.urgency, URGENCY_EMERGENCY)

    def test_two_red_flags_trigger_emergency(self):
        answers = self._all_no()
        answers["chest_pain"] = "sim"
        answers["breathing_difficulty"] = "sim"
        decision = evaluate("Dor no peito.", answers)
        self.assertEqual(decision.urgency, URGENCY_EMERGENCY)
        # Note: "dor no peito" is also an emergency keyword → rationale is keyword
        self.assertIn("dor no peito", " ".join(decision.matched_keywords))

    def test_single_red_flag_is_urgent(self):
        answers = self._all_no()
        answers["severe_pain"] = "sim"
        decision = evaluate("Dor de cabeça.", answers)
        self.assertEqual(decision.urgency, URGENCY_URGENT)

    def test_urgent_keyword_alone_is_urgent(self):
        decision = evaluate("Febre alta desde ontem.", self._all_no())
        self.assertEqual(decision.urgency, URGENCY_URGENT)

    def test_missing_answers_treated_as_no(self):
        # Defensive: empty answers map should classify as routine.
        decision = evaluate("Dor leve.", {})
        self.assertEqual(decision.urgency, URGENCY_ROUTINE)


# ─── Session FSM + REST tests ─────────────────────────────────────────────────


class TriageSessionFSMTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="triage",
            defaults={"is_enabled": True},
        )
        self.user = _make_user(
            role_name="triage_responder",
            perms=["triage.read", "triage.respond"],
        )
        self.reader = _make_user(role_name="triage_reader", perms=["triage.read"])
        self.client.force_authenticate(user=self.user)

    def _yes_to_all(self, session_id, *, except_altered=True):
        for q in RED_FLAG_QUESTIONS:
            value = "não" if q.key == "altered_consciousness" and except_altered else "sim"
            self.client.post(_answer(session_id), {"key": q.key, "value": value}, format="json")

    def _create_session(self):
        return self.client.post(
            SESSIONS_URL,
            {"contact_phone": "11999999999", "chief_complaint": "Dor de cabeça."},
            format="json",
        )

    # Question bank

    def test_question_bank_endpoint(self):
        resp = self.client.get(QUESTIONS_URL)
        self.assertEqual(resp.status_code, 200)
        keys = {q["key"] for q in resp.data}
        self.assertEqual(keys, set(question_keys()))

    # Create + state

    def test_create_session_returns_first_question(self):
        resp = self._create_session()
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["status"], "started")
        self.assertIsNotNone(resp.data["next_question"])
        self.assertEqual(resp.data["next_question"]["key"], "chest_pain")

    def test_chief_complaint_patch(self):
        resp = self._create_session()
        sid = resp.data["id"]
        r = self.client.patch(_complaint(sid), {"chief_complaint": "Tosse seca."}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["chief_complaint"], "Tosse seca.")
        # Status moves to `answering` once any input lands.
        self.assertEqual(r.data["status"], "answering")

    def test_answer_writes_into_session(self):
        sid = self._create_session().data["id"]
        r = self.client.post(_answer(sid), {"key": "chest_pain", "value": "não"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["answers"]["chest_pain"], "não")
        # Next question advances
        self.assertEqual(r.data["next_question"]["key"], "breathing_difficulty")

    def test_answer_unknown_key_rejected_at_serializer(self):
        sid = self._create_session().data["id"]
        r = self.client.post(_answer(sid), {"key": "weird", "value": "sim"}, format="json")
        self.assertEqual(r.status_code, 400)

    # Evaluate transitions

    def test_evaluate_before_all_answered_returns_409(self):
        sid = self._create_session().data["id"]
        r = self.client.post(_evaluate(sid))
        self.assertEqual(r.status_code, 409)

    def test_evaluate_routine_path(self):
        sid = self._create_session().data["id"]
        for q in RED_FLAG_QUESTIONS:
            value = "sim" if q.key == "altered_consciousness" else "não"
            self.client.post(_answer(sid), {"key": q.key, "value": value}, format="json")
        r = self.client.post(_evaluate(sid))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["urgency"], "routine")
        self.assertEqual(r.data["status"], "evaluated")

    def test_evaluate_emergency_escalates_automatically(self):
        sid = self._create_session().data["id"]
        # 2 red flags positive → emergency
        for q in RED_FLAG_QUESTIONS:
            value = (
                "sim"
                if q.key in {"chest_pain", "breathing_difficulty"}
                else "sim"
                if q.key == "altered_consciousness"
                else "não"
            )
            self.client.post(_answer(sid), {"key": q.key, "value": value}, format="json")
        r = self.client.post(_evaluate(sid))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["urgency"], "emergency")
        self.assertEqual(r.data["status"], "escalated")
        self.assertIsNotNone(r.data["escalated_at"])

    def test_double_evaluate_returns_409(self):
        sid = self._create_session().data["id"]
        for q in RED_FLAG_QUESTIONS:
            value = "sim" if q.key == "altered_consciousness" else "não"
            self.client.post(_answer(sid), {"key": q.key, "value": value}, format="json")
        self.client.post(_evaluate(sid))
        r = self.client.post(_evaluate(sid))
        self.assertEqual(r.status_code, 409)

    # Complete / cancel

    def test_complete_after_evaluation(self):
        sid = self._create_session().data["id"]
        for q in RED_FLAG_QUESTIONS:
            value = "sim" if q.key == "altered_consciousness" else "não"
            self.client.post(_answer(sid), {"key": q.key, "value": value}, format="json")
        self.client.post(_evaluate(sid))
        r = self.client.post(_complete(sid))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "completed")
        self.assertIsNotNone(r.data["closed_at"])

    def test_cancel_from_started(self):
        sid = self._create_session().data["id"]
        r = self.client.post(_cancel(sid))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "cancelled")

    def test_complete_before_evaluation_returns_409(self):
        sid = self._create_session().data["id"]
        r = self.client.post(_complete(sid))
        self.assertEqual(r.status_code, 409)

    # List filtering

    def test_list_filters_by_urgency(self):
        # Build one routine session and one emergency session.
        r1 = self._create_session().data["id"]
        for q in RED_FLAG_QUESTIONS:
            value = "sim" if q.key == "altered_consciousness" else "não"
            self.client.post(_answer(r1), {"key": q.key, "value": value}, format="json")
        self.client.post(_evaluate(r1))

        e1 = self._create_session().data["id"]
        for q in RED_FLAG_QUESTIONS:
            if q.key == "altered_consciousness":
                value = "sim"
            elif q.key in {"chest_pain", "breathing_difficulty"}:
                value = "sim"
            else:
                value = "não"
            self.client.post(_answer(e1), {"key": q.key, "value": value}, format="json")
        self.client.post(_evaluate(e1))

        resp = self.client.get(SESSIONS_URL, {"urgency": "emergency"})
        ids = {entry["id"] for entry in resp.data}
        self.assertIn(e1, ids)
        self.assertNotIn(r1, ids)

    # Gates

    def test_create_blocked_for_read_only_role(self):
        self.client.force_authenticate(user=self.reader)
        resp = self._create_session()
        self.assertEqual(resp.status_code, 403)

    def test_blocked_when_module_disabled(self):
        FeatureFlag.objects.filter(tenant=self.__class__.tenant, module_key="triage").update(
            is_enabled=False
        )
        resp = self.client.get(SESSIONS_URL)
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.get(SESSIONS_URL)
        self.assertIn(resp.status_code, [401, 403])

    def test_terminal_state_rejects_further_answers(self):
        sid = self._create_session().data["id"]
        self.client.post(_cancel(sid))
        # Try to answer after cancel
        r = self.client.post(_answer(sid), {"key": "chest_pain", "value": "sim"}, format="json")
        self.assertEqual(r.status_code, 409)


# ─── Abandonment (partial evaluation) unit tests ──────────────────────────────


class TriageAbandonTest(TenantTestCase):
    """`abandon()` must escalate an emergency visible in partial evidence."""

    def test_abandon_with_emergency_complaint_escalates(self):
        ts = TriageSession.objects.create(contact_phone="5511999990001")
        ts.record_chief_complaint("estou com dor no peito")
        emergency = ts.abandon("session_expired")
        ts.refresh_from_db()
        self.assertTrue(emergency)
        self.assertEqual(ts.status, TriageSession.STATUS_ESCALATED)
        self.assertEqual(ts.urgency, URGENCY_EMERGENCY)
        self.assertIsNotNone(ts.escalated_at)
        self.assertIsNotNone(ts.closed_at)
        self.assertIn("abandoned: session_expired", ts.rationale)

    def test_abandon_without_emergency_cancels(self):
        ts = TriageSession.objects.create(contact_phone="5511999990002")
        ts.record_chief_complaint("dor de garganta leve")
        emergency = ts.abandon("opted_out")
        ts.refresh_from_db()
        self.assertFalse(emergency)
        self.assertEqual(ts.status, TriageSession.STATUS_CANCELLED)
        self.assertIsNone(ts.escalated_at)
        self.assertIsNotNone(ts.closed_at)

    def test_abandon_before_complaint_cancels_quietly(self):
        ts = TriageSession.objects.create(contact_phone="5511999990003")
        self.assertFalse(ts.abandon("session_expired"))
        ts.refresh_from_db()
        self.assertEqual(ts.status, TriageSession.STATUS_CANCELLED)

    def test_abandon_is_noop_on_terminal_sessions(self):
        ts = TriageSession.objects.create(contact_phone="5511999990004")
        ts.record_chief_complaint("estou com dor no peito")
        self.assertTrue(ts.abandon("first"))
        ts.refresh_from_db()
        escalated_at = ts.escalated_at
        # Second abandon must not double-report the emergency nor mutate state.
        self.assertFalse(ts.abandon("second"))
        ts.refresh_from_db()
        self.assertEqual(ts.status, TriageSession.STATUS_ESCALATED)
        self.assertEqual(ts.escalated_at, escalated_at)


# Use TriageSession to keep the import live for type checkers
_ = TriageSession
