"""
S-056 tests: EmailService — confirmation and reminder emails.
Uses Django's test email backend (in-memory outbox).
"""
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from apps.core.models import User
from apps.emr.models import Appointment, Patient, Professional


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="noreply@vitali.test",
)
class EmailServiceTest(TenantTestCase):
    """EmailService unit tests — confirmation + reminder emails."""

    def setUp(self):
        mail.outbox = []
        self.user = User.objects.create_user(
            email="doc@email.test",
            password="pass1234",
            schema_name=self.tenant.schema_name,
        )
        self.patient = Patient.objects.create(
            full_name="Maria Souza",
            date_of_birth="1980-03-20",
            sex="F",
            email="maria@email.test",
        )
        self.professional = Professional.objects.create(
            user=self.user,
            council_type="CRM",
            council_number="55555",
            council_state="SP",
        )
        now = timezone.now()
        self.appointment = Appointment.objects.create(
            patient=self.patient,
            professional=self.professional,
            start_time=now + timezone.timedelta(days=1, hours=10),
            end_time=now + timezone.timedelta(days=1, hours=11),
            status="confirmed",
        )

    def test_confirmation_email_sent(self):
        """send_appointment_confirmation sends email to patient."""
        from apps.core.services.email import EmailService
        result = EmailService.send_appointment_confirmation(self.appointment)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("confirmada", mail.outbox[0].subject.lower())
        self.assertEqual(mail.outbox[0].to, ["maria@email.test"])

    def test_reminder_email_sent(self):
        """send_appointment_reminder sends reminder email to patient."""
        from apps.core.services.email import EmailService
        result = EmailService.send_appointment_reminder(self.appointment)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("lembrete", mail.outbox[0].subject.lower())

    def test_no_email_when_patient_has_no_email(self):
        """Returns False and sends nothing when patient email is blank."""
        from apps.core.services.email import EmailService
        self.patient.email = ""
        self.patient.save(update_fields=["email"])
        result = EmailService.send_appointment_confirmation(self.appointment)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_email_contains_patient_name(self):
        """Confirmation email body contains patient full name."""
        from apps.core.services.email import EmailService
        EmailService.send_appointment_confirmation(self.appointment)
        body = mail.outbox[0].body
        self.assertIn("Maria Souza", body)
