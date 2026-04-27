"""Sprint 19 / S-080 — PatientRegistrationService unit tests.

Covers:
- AuditLog chain with correlation_id (decision 2A)
- WhatsAppContact created with opt_in=False (LGPD posture B, decision D2)
- No contact created when patient has no phone/whatsapp
- Idempotent re-registration of the same phone number
- Re-link of existing WhatsAppContact to a new patient (same phone)
- Phone priority: patient.whatsapp wins over patient.phone
- Fallback to patient.phone when patient.whatsapp is empty
"""

from datetime import date

from apps.core.models import AuditLog, User
from apps.emr.models import Patient
from apps.emr.services.patient_registration import PatientRegistrationService
from apps.test_utils import TenantTestCase
from apps.whatsapp.models import WhatsAppContact

# ── Helpers ───────────────────────────────────────────────────────────────────


def _requesting_user():
    """Return (or create) a superuser that acts as the request actor."""
    user, _ = User.objects.get_or_create(
        email="registrar@example.com",
        defaults={"full_name": "System Registrar", "is_staff": True},
    )
    return user


def _make_patient(
    full_name="Ana Souza",
    cpf="111.222.333-44",
    phone="",
    whatsapp="",
    **kwargs,
):
    """Create and return a minimal Patient instance."""
    return Patient.objects.create(
        full_name=full_name,
        cpf=cpf,
        birth_date=date(1990, 1, 1),
        gender="F",
        phone=phone,
        whatsapp=whatsapp,
        **kwargs,
    )


# ── Test Cases ────────────────────────────────────────────────────────────────


class TestPatientRegistrationService(TenantTestCase):
    """All tests share the fast_test tenant schema."""

    def setUp(self):
        self.requester = _requesting_user()
        self.service = PatientRegistrationService(requesting_user=self.requester)

    # ── 1. AuditLog with correlation_id ──────────────────────────────────────

    def test_register_creates_audit_log_with_correlation_id(self):
        patient = _make_patient(full_name="Beatriz Lima", phone="+5511900000001")
        self.service.register(patient)

        logs = AuditLog.objects.filter(
            resource_type="patient",
            resource_id=str(patient.id),
        )
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.action, "patient_created")
        self.assertIn("correlation_id", log.new_data)
        self.assertEqual(log.new_data["correlation_id"], self.service.correlation_id)

    # ── 2. WhatsAppContact created with opt_in=False ──────────────────────────

    def test_register_creates_whatsapp_contact_with_opt_in_false(self):
        phone = "+5511900000002"
        patient = _make_patient(full_name="Carlos Mendes", phone=phone)
        self.service.register(patient)

        contact = WhatsAppContact.objects.get(phone=phone)
        self.assertFalse(contact.opt_in)
        self.assertEqual(contact.patient_id, patient.id)

    # ── 3. No phone → no contact created ─────────────────────────────────────

    def test_register_no_phone_no_contact_created(self):
        patient = _make_patient(full_name="Daria Nunes", phone="", whatsapp="")
        before = WhatsAppContact.objects.count()
        self.service.register(patient)
        after = WhatsAppContact.objects.count()
        self.assertEqual(before, after)

    # ── 4. Idempotent: same phone reuses existing contact ────────────────────

    def test_register_idempotent_same_phone_reuses_contact(self):
        """Calling register twice for the same patient must not create a second WhatsAppContact."""
        phone = "+5511900000004"
        patient = _make_patient(full_name="Eduardo Costa", phone=phone)

        svc1 = PatientRegistrationService(requesting_user=self.requester)
        svc1.register(patient)

        before = WhatsAppContact.objects.filter(phone=phone).count()

        svc2 = PatientRegistrationService(requesting_user=self.requester)
        svc2.register(patient)

        after = WhatsAppContact.objects.filter(phone=phone).count()

        self.assertEqual(before, 1)
        self.assertEqual(after, 1)

    # ── 5. Re-link existing contact to new patient ────────────────────────────

    def test_register_relinks_existing_contact_to_new_patient(self):
        """
        If a WhatsAppContact already exists for a phone number pointing at an old
        patient, registering a new patient with the same phone should re-link the
        contact to the new patient.
        """
        phone = "+5511900000005"
        old_patient = _make_patient(full_name="Old Patient", phone=phone)
        WhatsAppContact.objects.create(phone=phone, patient=old_patient, opt_in=False)

        new_patient = _make_patient(full_name="New Patient", phone=phone, cpf="999.888.777-66")
        svc = PatientRegistrationService(requesting_user=self.requester)
        svc.register(new_patient)

        contact = WhatsAppContact.objects.get(phone=phone)
        self.assertEqual(contact.patient_id, new_patient.id)
        # Still exactly one contact row for this phone
        self.assertEqual(WhatsAppContact.objects.filter(phone=phone).count(), 1)

    # ── 6. whatsapp field wins over phone ─────────────────────────────────────

    def test_register_uses_whatsapp_field_when_set(self):
        wa_number = "+5511999000006"
        phone_number = "+5511888000006"
        patient = _make_patient(
            full_name="Fernanda Rocha",
            whatsapp=wa_number,
            phone=phone_number,
            cpf="100.200.300-00",
        )
        svc = PatientRegistrationService(requesting_user=self.requester)
        svc.register(patient)

        # Contact must be created for the whatsapp number, not the phone fallback
        self.assertTrue(WhatsAppContact.objects.filter(phone=wa_number).exists())
        self.assertFalse(WhatsAppContact.objects.filter(phone=phone_number).exists())

    # ── 7. Fallback to phone when whatsapp is empty ───────────────────────────

    def test_register_falls_back_to_phone_when_whatsapp_empty(self):
        phone_number = "+5511888000007"
        patient = _make_patient(
            full_name="Gustavo Pires",
            whatsapp="",
            phone=phone_number,
            cpf="200.300.400-00",
        )
        svc = PatientRegistrationService(requesting_user=self.requester)
        svc.register(patient)

        self.assertTrue(WhatsAppContact.objects.filter(phone=phone_number).exists())
