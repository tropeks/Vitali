"""Sprint 21 / S-100 — EncounterSigningService unit tests.

Covers:
  - AuditLog written with correlation_id (decision 2A)
  - Opted-in contact → apply_async called with countdown=86400 + followup_scheduled audit
  - Opted-out contact → no apply_async + followup_skipped audit
  - No contact at all → same skip behavior
  - Already-signed encounter → ValueError raised
"""

from datetime import date
from unittest.mock import MagicMock, patch

from apps.core.models import AuditLog, User
from apps.emr.models import Encounter, Patient, Professional
from apps.emr.services.encounter_signing import FOLLOWUP_DELAY_SECONDS, EncounterSigningService
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import WhatsAppContact

# ── Helpers ────────────────────────────────────────────────────────────────────

_TASK_PATCH = "apps.emr.services.encounter_signing.send_post_visit_followup_whatsapp"


def _requesting_user():
    user, _ = User.objects.get_or_create(
        email="doctor@example.com",
        defaults={"full_name": "Dr. Test", "is_staff": False},
    )
    return user


def _make_patient(full_name="Ana Lima", cpf="111.222.333-44", whatsapp=""):
    return Patient.objects.create(
        full_name=full_name,
        cpf=cpf,
        birth_date=date(1990, 1, 15),
        gender="F",
        whatsapp=whatsapp,
    )


def _make_professional(email="prof@clinic.com", suffix="001"):
    user, _ = User.objects.get_or_create(
        email=email,
        defaults={"full_name": f"Dr. Prof {suffix}"},
    )
    prof, _ = Professional.objects.get_or_create(
        user=user,
        defaults={
            "council_type": "CRM",
            "council_number": f"CRM{suffix}",
            "council_state": "SP",
        },
    )
    return prof


def _make_encounter(patient, professional, status="open"):
    return Encounter.objects.create(
        patient=patient,
        professional=professional,
        status=status,
        chief_complaint="Dor de cabeça",
    )


# ── Test Cases ─────────────────────────────────────────────────────────────────


class TestEncounterSigningService(TenantTestCase):
    def setUp(self):
        self.requester = _requesting_user()
        self.patient = _make_patient()
        self.professional = _make_professional()

    # ── 1. AuditLog with correlation_id ────────────────────────────────────────

    def test_sign_encounter_writes_audit_with_correlation_id(self):
        """encounter_signed AuditLog is written with the service's correlation_id."""
        encounter = _make_encounter(self.patient, self.professional)
        service = EncounterSigningService(requesting_user=self.requester)

        with patch(_TASK_PATCH):
            service.sign(encounter)

        log = AuditLog.objects.filter(
            action="encounter_signed",
            resource_type="encounter",
            resource_id=str(encounter.id),
        ).first()
        self.assertIsNotNone(log, "encounter_signed AuditLog must be written")
        self.assertIn("correlation_id", log.new_data)
        self.assertEqual(log.new_data["correlation_id"], service.correlation_id)
        self.assertEqual(log.new_data["patient_id"], str(encounter.patient_id))
        self.assertEqual(log.new_data["professional_id"], str(encounter.professional_id))
        self.assertIn("signed_at", log.new_data)

    # ── 2. Opted-in contact → apply_async + followup_scheduled audit ──────────

    def test_sign_encounter_with_opted_in_contact_schedules_followup(self):
        """Patient with opt_in=True → apply_async called with countdown=86400 + followup_scheduled."""
        WhatsAppContact.objects.create(
            phone="+5511911111111",
            patient=self.patient,
            opt_in=True,
        )
        encounter = _make_encounter(self.patient, self.professional)
        service = EncounterSigningService(requesting_user=self.requester)

        mock_task = MagicMock()
        with patch(_TASK_PATCH, mock_task):
            with self.captureOnCommitCallbacks(execute=True):
                service.sign(encounter)

        mock_task.apply_async.assert_called_once_with(
            args=[str(encounter.id), service.correlation_id],
            countdown=FOLLOWUP_DELAY_SECONDS,
        )

        # followup_scheduled audit written
        scheduled_audit = AuditLog.objects.filter(
            action="followup_scheduled",
            resource_type="encounter",
            resource_id=str(encounter.id),
        ).first()
        self.assertIsNotNone(scheduled_audit, "followup_scheduled AuditLog must be written")
        self.assertEqual(scheduled_audit.new_data["correlation_id"], service.correlation_id)
        self.assertEqual(
            scheduled_audit.new_data["countdown_seconds"],
            FOLLOWUP_DELAY_SECONDS,
        )

        # No followup_skipped audit
        self.assertFalse(
            AuditLog.objects.filter(
                action="followup_skipped",
                resource_type="encounter",
                resource_id=str(encounter.id),
            ).exists(),
        )

    # ── 3. Opted-out contact → skip ───────────────────────────────────────────

    def test_sign_encounter_no_opted_in_contact_skips_followup(self):
        """Patient with opt_in=False → no apply_async + followup_skipped audit."""
        WhatsAppContact.objects.create(
            phone="+5511922222222",
            patient=self.patient,
            opt_in=False,
        )
        encounter = _make_encounter(self.patient, self.professional)
        service = EncounterSigningService(requesting_user=self.requester)

        mock_task = MagicMock()
        with patch(_TASK_PATCH, mock_task):
            service.sign(encounter)

        mock_task.apply_async.assert_not_called()

        skipped_audit = AuditLog.objects.filter(
            action="followup_skipped",
            resource_type="encounter",
            resource_id=str(encounter.id),
        ).first()
        self.assertIsNotNone(skipped_audit, "followup_skipped AuditLog must be written")
        self.assertEqual(skipped_audit.new_data["reason"], "no_opted_in_contact")
        self.assertEqual(skipped_audit.new_data["correlation_id"], service.correlation_id)

    # ── 4. No contact at all → skip ───────────────────────────────────────────

    def test_sign_encounter_with_no_contact_at_all_skips(self):
        """Patient with no WhatsAppContact at all → same skip behavior as opted-out."""
        patient2 = _make_patient(full_name="Sem Contato", cpf="999.888.777-00")
        encounter = _make_encounter(patient2, self.professional)
        service = EncounterSigningService(requesting_user=self.requester)

        mock_task = MagicMock()
        with patch(_TASK_PATCH, mock_task):
            service.sign(encounter)

        mock_task.apply_async.assert_not_called()

        skipped_audit = AuditLog.objects.filter(
            action="followup_skipped",
            resource_type="encounter",
            resource_id=str(encounter.id),
        ).first()
        self.assertIsNotNone(skipped_audit, "followup_skipped AuditLog must be written")
        self.assertEqual(skipped_audit.new_data["reason"], "no_opted_in_contact")

    # ── 5. Already-signed encounter → ValueError ──────────────────────────────

    def test_sign_encounter_already_signed_raises(self):
        """Calling service.sign on a non-open encounter raises ValueError."""
        encounter = _make_encounter(self.patient, self.professional, status="signed")
        service = EncounterSigningService(requesting_user=self.requester)

        with self.assertRaises(ValueError) as ctx:
            service.sign(encounter)

        self.assertIn("abertas", str(ctx.exception))

    # ── 6. Encounter fields set correctly after sign ──────────────────────────

    def test_sign_encounter_sets_status_signed_at_signed_by(self):
        """After sign(), encounter.status='signed', signed_at is set, signed_by is requester."""
        encounter = _make_encounter(self.patient, self.professional)
        service = EncounterSigningService(requesting_user=self.requester)

        with patch(_TASK_PATCH):
            result = service.sign(encounter)

        self.assertEqual(result.status, "signed")
        self.assertIsNotNone(result.signed_at)
        self.assertEqual(result.signed_by, self.requester)

        # Persisted to DB
        encounter.refresh_from_db()
        self.assertEqual(encounter.status, "signed")
        self.assertIsNotNone(encounter.signed_at)
        self.assertEqual(encounter.signed_by_id, self.requester.id)
