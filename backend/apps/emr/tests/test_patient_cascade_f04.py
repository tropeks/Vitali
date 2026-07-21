"""F-04 (E-013) — Patient registration cascade integration tests.

End-to-end coverage of the cascade fired when a Patient is created:
  1. Patient with a WhatsApp number (module active + cold opt-in flag on) →
     WhatsAppContact created and the welcome + opt-in invitation dispatched
     (async, < 30s).
  2. Gate 1: the WhatsApp cascade only runs when the tenant's whatsapp module
     is on (fail-closed, including when tenant resolution itself blows up).
  3. Gate 2: the opt-in invitation dispatch additionally requires the
     default-OFF ``whatsapp_cold_optin`` flag (cold outbound ban-risk gate).
  4. No MedicalHistory placeholder is ever pre-created (pre-merge review of
     PR #145: the model is a list of clinical entries; a blank row would
     permanently pollute every new patient's chart).

Plus unit coverage of the send_opt_in_invitation Celery task (happy path,
opt-in/opt-out no-ops, and fail-open on exhausted retries).

Harness notes (mirror test_opt_in_cascade.py):
- FastTenantTestCase wraps each test in a savepoint, so transaction.on_commit
  callbacks never fire. We patch the service's transaction.on_commit to run the
  callback immediately when we want to observe the .delay() dispatch.
- send_opt_in_invitation.__wrapped__ is the bound task method; call it as
  __wrapped__(contact_id, correlation_id).
- The task imports get_gateway inside its body, so patch the source:
  apps.whatsapp.gateway.get_gateway.
"""

from datetime import date
from unittest.mock import MagicMock, PropertyMock, patch

from apps.core.models import AuditLog, FeatureFlag, User
from apps.emr.models import MedicalHistory, Patient
from apps.emr.services.patient_registration import PatientRegistrationService
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import ConversationSession, WhatsAppContact
from apps.whatsapp.tasks import send_opt_in_invitation

# ── Helpers ─────────────────────────────────────────────────────────────────


def _requester():
    user, _ = User.objects.get_or_create(
        email="f04-registrar@example.com",
        defaults={"full_name": "F04 Registrar", "is_staff": True},
    )
    return user


def _make_patient(full_name="Joana Prado", cpf="529.982.247-25", phone="", whatsapp=""):
    return Patient.objects.create(
        full_name=full_name,
        cpf=cpf,
        birth_date=date(1990, 5, 20),
        gender="F",
        phone=phone,
        whatsapp=whatsapp,
    )


def _set_flag(tenant, module_key, enabled):
    FeatureFlag.objects.update_or_create(
        tenant=tenant,
        module_key=module_key,
        defaults={"is_enabled": enabled},
    )


def _set_whatsapp_module(tenant, enabled):
    _set_flag(tenant, "whatsapp", enabled)


def _set_cold_optin(tenant, enabled):
    _set_flag(tenant, "whatsapp_cold_optin", enabled)


# ── Cascade integration ─────────────────────────────────────────────────────


class PatientCascadeF04Tests(TenantTestCase):
    def setUp(self):
        self.requester = _requester()

    def _register(self, patient):
        return PatientRegistrationService(requesting_user=self.requester).register(patient)

    def test_full_cascade_with_whatsapp_module_active(self):
        """Module on + cold opt-in flag on + WhatsApp number → contact created,
        invitation dispatched, and NO MedicalHistory placeholder."""
        _set_whatsapp_module(self.__class__.tenant, True)
        _set_cold_optin(self.__class__.tenant, True)
        patient = _make_patient(whatsapp="5511910000001")

        with (
            patch(
                "apps.emr.services.patient_registration.transaction.on_commit",
                side_effect=lambda fn: fn(),
            ),
            patch("apps.whatsapp.tasks.send_opt_in_invitation.delay") as mock_delay,
        ):
            self._register(patient)

        # WhatsAppContact created, opt-in not yet granted.
        contact = WhatsAppContact.objects.get(phone="5511910000001")
        self.assertFalse(contact.opt_in)
        self.assertEqual(contact.patient_id, patient.id)

        # Opt-in invitation dispatched exactly once with (contact_id, correlation_id).
        mock_delay.assert_called_once()
        args = mock_delay.call_args[0]
        self.assertEqual(args[0], str(contact.id))
        self.assertIsNotNone(args[1])

        # No MedicalHistory placeholder — real entries are POSTed on demand.
        self.assertFalse(MedicalHistory.objects.filter(patient=patient).exists())

        # Audit trail covers each cascade step.
        actions = set(
            AuditLog.objects.filter(
                new_data__correlation_id=args[1],
            ).values_list("action", flat=True)
        )
        self.assertTrue(
            {
                "patient_created",
                "whatsapp_contact_mapped",
                "opt_in_invitation_enqueued",
            }.issubset(actions)
        )

    def test_cold_optin_flag_off_blocks_invitation(self):
        """Module on but whatsapp_cold_optin off (default) → contact is still
        mapped, but the cold outbound invitation is NOT enqueued."""
        _set_whatsapp_module(self.__class__.tenant, True)
        # No whatsapp_cold_optin row at all: the flag is default-OFF.
        patient = _make_patient(whatsapp="5511910000005", cpf="004.690.418-20")

        with (
            patch(
                "apps.emr.services.patient_registration.transaction.on_commit",
                side_effect=lambda fn: fn(),
            ),
            patch("apps.whatsapp.tasks.send_opt_in_invitation.delay") as mock_delay,
        ):
            self._register(patient)

        # Contact mapping still happens (that part is safe).
        contact = WhatsAppContact.objects.get(phone="5511910000005")
        self.assertEqual(contact.patient_id, patient.id)

        # But nothing is dispatched and no enqueue audit is written.
        mock_delay.assert_not_called()
        self.assertFalse(
            AuditLog.objects.filter(
                action="opt_in_invitation_enqueued",
                resource_id=str(contact.id),
            ).exists()
        )

    def test_cold_optin_flag_explicitly_disabled_blocks_invitation(self):
        """An explicit is_enabled=False row behaves the same as no row."""
        _set_whatsapp_module(self.__class__.tenant, True)
        _set_cold_optin(self.__class__.tenant, False)
        patient = _make_patient(whatsapp="5511910000006", cpf="871.379.833-40")

        with (
            patch(
                "apps.emr.services.patient_registration.transaction.on_commit",
                side_effect=lambda fn: fn(),
            ),
            patch("apps.whatsapp.tasks.send_opt_in_invitation.delay") as mock_delay,
        ):
            self._register(patient)

        self.assertTrue(WhatsAppContact.objects.filter(phone="5511910000006").exists())
        mock_delay.assert_not_called()

    def test_module_off_no_whatsapp_side_effects(self):
        """Gate closed → no WhatsAppContact, no invitation."""
        _set_whatsapp_module(self.__class__.tenant, False)
        patient = _make_patient(whatsapp="5511910000002", cpf="111.444.777-35")

        with patch("apps.whatsapp.tasks.send_opt_in_invitation.delay") as mock_delay:
            self._register(patient)

        self.assertFalse(WhatsAppContact.objects.filter(phone="5511910000002").exists())
        mock_delay.assert_not_called()
        # Patient creation itself is still audited.
        self.assertTrue(
            AuditLog.objects.filter(action="patient_created", resource_id=str(patient.id)).exists()
        )

    def test_fail_closed_when_tenant_resolution_raises(self):
        """_whatsapp_module_active fail-closed path: connection.tenant blowing up
        must NOT break patient registration — it just skips the WhatsApp cascade."""
        _set_whatsapp_module(self.__class__.tenant, True)
        _set_cold_optin(self.__class__.tenant, True)
        patient = _make_patient(whatsapp="5511910000007", cpf="616.929.166-90")

        mock_connection = MagicMock()
        type(mock_connection).tenant = PropertyMock(
            side_effect=RuntimeError("no tenant on connection")
        )
        with (
            patch(
                "apps.emr.services.patient_registration.connection",
                mock_connection,
            ),
            patch("apps.whatsapp.tasks.send_opt_in_invitation.delay") as mock_delay,
        ):
            result = self._register(patient)

        # Registration completed and returned the patient unchanged.
        self.assertEqual(result.id, patient.id)
        self.assertTrue(
            AuditLog.objects.filter(action="patient_created", resource_id=str(patient.id)).exists()
        )
        # WhatsApp cascade fully skipped.
        self.assertFalse(WhatsAppContact.objects.filter(phone="5511910000007").exists())
        mock_delay.assert_not_called()

    def test_no_phone_no_contact(self):
        """No phone/whatsapp at all → no contact, registration still completes."""
        _set_whatsapp_module(self.__class__.tenant, True)
        patient = _make_patient(cpf="390.533.447-05")

        before = WhatsAppContact.objects.count()
        self._register(patient)

        self.assertEqual(WhatsAppContact.objects.count(), before)
        self.assertTrue(
            AuditLog.objects.filter(action="patient_created", resource_id=str(patient.id)).exists()
        )

    def test_no_medical_history_placeholder_ever_created(self):
        """Registration (even repeated) never fabricates MedicalHistory rows."""
        _set_whatsapp_module(self.__class__.tenant, True)
        patient = _make_patient(whatsapp="5511910000003", cpf="901.452.467-90")

        # on_commit fires immediately here, so .delay must be mocked across BOTH
        # registrations to avoid hitting the real Celery backend.
        with (
            patch(
                "apps.emr.services.patient_registration.transaction.on_commit",
                side_effect=lambda fn: fn(),
            ),
            patch("apps.whatsapp.tasks.send_opt_in_invitation.delay"),
        ):
            self._register(patient)
            self._register(patient)

        self.assertEqual(MedicalHistory.objects.filter(patient=patient).count(), 0)

    def test_invitation_not_sent_for_existing_contact(self):
        """Re-registering a phone that already has a contact must not re-invite."""
        _set_whatsapp_module(self.__class__.tenant, True)
        _set_cold_optin(self.__class__.tenant, True)
        phone = "5511910000004"
        first = _make_patient(whatsapp=phone, cpf="153.509.460-56")
        WhatsAppContact.objects.create(phone=phone, patient=first, opt_in=False)

        second = _make_patient(full_name="Outro Paciente", whatsapp=phone, cpf="248.438.530-09")
        with (
            patch(
                "apps.emr.services.patient_registration.transaction.on_commit",
                side_effect=lambda fn: fn(),
            ),
            patch("apps.whatsapp.tasks.send_opt_in_invitation.delay") as mock_delay,
        ):
            self._register(second)

        mock_delay.assert_not_called()
        # Contact re-linked to the new patient, still a single row.
        self.assertEqual(WhatsAppContact.objects.filter(phone=phone).count(), 1)
        self.assertEqual(WhatsAppContact.objects.get(phone=phone).patient_id, second.id)


# ── send_opt_in_invitation task ─────────────────────────────────────────────


class OptInInvitationTaskTests(TenantTestCase):
    def _contact(self, phone="5511920000001", cpf="529.982.247-25", **kwargs):
        patient = _make_patient(whatsapp=phone, cpf=cpf)
        return WhatsAppContact.objects.create(phone=phone, patient=patient, **kwargs)

    def test_invitation_happy_path(self):
        """Sends the consent message, parks the session in PENDING_OPTIN, audits sent."""
        contact = self._contact()
        mock_gateway = MagicMock()
        with patch("apps.whatsapp.gateway.get_gateway", return_value=mock_gateway):
            send_opt_in_invitation.__wrapped__(str(contact.id), "corr-invite")

        mock_gateway.send_text.assert_called_once()
        to, text = mock_gateway.send_text.call_args[0]
        self.assertEqual(to, contact.phone)
        self.assertIn("Joana Prado", text)  # personalised greeting
        self.assertIn("LGPD", text)  # consent copy

        session = ConversationSession.objects.get(contact=contact)
        self.assertEqual(session.state, "PENDING_OPTIN")

        self.assertTrue(
            AuditLog.objects.filter(
                action="opt_in_invitation_sent",
                resource_id=str(contact.id),
                new_data__correlation_id="corr-invite",
            ).exists()
        )

    def test_invitation_noop_when_already_opted_in(self):
        contact = self._contact(phone="5511920000002", cpf="111.444.777-35", opt_in=True)
        mock_gateway = MagicMock()
        with patch("apps.whatsapp.gateway.get_gateway", return_value=mock_gateway):
            send_opt_in_invitation.__wrapped__(str(contact.id), "corr-noop")

        mock_gateway.send_text.assert_not_called()

    def test_invitation_noop_when_previously_opted_out(self):
        from django.utils import timezone

        contact = self._contact(phone="5511920000003", cpf="390.533.447-05")
        contact.opt_out_at = timezone.now()
        contact.save(update_fields=["opt_out_at"])

        mock_gateway = MagicMock()
        with patch("apps.whatsapp.gateway.get_gateway", return_value=mock_gateway):
            send_opt_in_invitation.__wrapped__(str(contact.id), "corr-out")

        mock_gateway.send_text.assert_not_called()

    def test_invitation_fail_open_writes_failed_audit(self):
        """Exhausted retries → opt_in_invitation_failed audit, no exception bubbles up."""
        from celery.exceptions import MaxRetriesExceededError

        contact = self._contact(phone="5511920000004", cpf="901.452.467-90")
        mock_gateway = MagicMock()
        mock_gateway.send_text.side_effect = RuntimeError("network down")

        with (
            patch("apps.whatsapp.gateway.get_gateway", return_value=mock_gateway),
            patch.object(send_opt_in_invitation, "retry", side_effect=MaxRetriesExceededError()),
        ):
            send_opt_in_invitation.__wrapped__(str(contact.id), "corr-fail")

        log = AuditLog.objects.get(
            action="opt_in_invitation_failed",
            resource_id=str(contact.id),
        )
        self.assertEqual(log.new_data["reason"], "max_retries_exceeded")
        self.assertEqual(log.new_data["correlation_id"], "corr-fail")
