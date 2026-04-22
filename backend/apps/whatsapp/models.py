"""
WhatsApp Patient Engagement — Models (Sprint 12, S-032/033/034/035)

Four models:
  WhatsAppContact  — one row per phone number, per tenant. Stores opt-in state.
  ConversationSession — EPHEMERAL. Deleted after appointment created or 30min timeout.
  MessageLog       — PERMANENT, PII-redacted audit trail for receptionist history view.
  ScheduledReminder — Tracks sent/pending reminder state per appointment per type.
"""

from django.db import models
from django.utils import timezone


class WhatsAppContact(models.Model):
    """One row per unique phone number in this tenant's schema."""

    phone = models.CharField(max_length=20, unique=True, db_index=True)
    patient = models.ForeignKey(
        "emr.Patient",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="whatsapp_contacts",
    )
    opt_in = models.BooleanField(default=False)
    opt_in_at = models.DateTimeField(null=True, blank=True)
    opt_out_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "WhatsApp Contact"
        verbose_name_plural = "WhatsApp Contacts"
        ordering = ["-created_at"]

    def __str__(self):
        name = self.patient.full_name if self.patient_id else "unknown"
        return f"{self.phone} ({name})"

    def do_opt_in(self):
        self.opt_in = True
        self.opt_in_at = timezone.now()
        self.opt_out_at = None
        self.save(update_fields=["opt_in", "opt_in_at", "opt_out_at"])

    def do_opt_out(self):
        self.opt_in = False
        self.opt_out_at = timezone.now()
        self.save(update_fields=["opt_in", "opt_out_at"])


class ConversationSession(models.Model):
    """
    EPHEMERAL. One active session per contact. Deleted after appointment created
    or after 30-minute idle timeout (cleanup_expired_sessions task).

    Use get_context() / set_context() from context.py to access the context
    JSONField — direct dict access risks key typos.
    """

    FSM_STATES = [
        ("IDLE", "Idle"),
        ("PENDING_OPTIN", "Pending opt-in"),
        ("SELECTING_SELF_OR_OTHER", "Selecting self or other"),
        ("CAPTURING_NAME", "Capturing other person name"),
        ("CAPTURING_CPF", "Capturing other person CPF"),
        ("SELECTING_SPECIALTY", "Selecting specialty"),
        ("SELECTING_PROFESSIONAL", "Selecting professional"),
        ("SELECTING_DATE", "Selecting date"),
        ("SELECTING_TIME", "Selecting time"),
        ("CONFIRMING", "Confirming booking"),
        ("CONFIRMED", "Booking confirmed"),
        ("FALLBACK_HUMAN", "Fallback to human"),
        ("OPTED_OUT", "Opted out"),
    ]

    contact = models.OneToOneField(
        WhatsAppContact,
        on_delete=models.CASCADE,
        related_name="session",
    )
    state = models.CharField(max_length=30, choices=FSM_STATES, default="IDLE")
    context = models.JSONField(default=dict)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conversation Session"
        indexes = [
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"Session({self.contact.phone}, {self.state})"

    def refresh_expiry(self):
        from datetime import timedelta

        self.expires_at = timezone.now() + timedelta(minutes=30)

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @classmethod
    def get_or_create_for_contact(cls, contact):
        """Get existing session or create a fresh IDLE one."""
        from datetime import timedelta

        session, created = cls.objects.get_or_create(
            contact=contact,
            defaults={
                "state": "IDLE",
                "context": {},
                "expires_at": timezone.now() + timedelta(minutes=30),
            },
        )
        return session, created


class MessageLog(models.Model):
    """
    PERMANENT audit trail. PII-redacted for LGPD compliance.
    Created for every inbound and outbound message (except pre-optin messages).
    CPF in content_preview is masked before saving.
    """

    DIRECTION_CHOICES = [("inbound", "Inbound"), ("outbound", "Outbound")]
    TYPE_CHOICES = [
        ("text", "Text"),
        ("button_reply", "Button reply"),
        ("template", "Template"),
        ("list_reply", "List reply"),
    ]

    contact = models.ForeignKey(
        WhatsAppContact,
        on_delete=models.CASCADE,
        related_name="message_logs",
    )
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    content_preview = models.CharField(max_length=200)  # CPF masked; first 200 chars
    message_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="text")
    appointment = models.ForeignKey(
        "emr.Appointment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="message_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Message Log"
        verbose_name_plural = "Message Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["contact", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.direction}] {self.contact.phone} — {self.content_preview[:50]}"


class ScheduledReminder(models.Model):
    """
    Tracks reminder send state. unique_together prevents duplicate sends.
    Celery tasks use select_for_update(skip_locked=True) to prevent
    concurrent worker double-send.
    """

    TYPE_CHOICES = [
        ("24h", "24h reminder"),
        ("2h", "2h reminder"),
        ("satisfaction", "Post-visit satisfaction survey"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("sent", "Sent"),
        ("failed", "Failed"),
        ("responded", "Responded"),
        ("skipped", "Skipped"),
    ]

    appointment = models.ForeignKey(
        "emr.Appointment",
        on_delete=models.CASCADE,
        related_name="scheduled_reminders",
    )
    reminder_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["appointment", "reminder_type"]]
        verbose_name = "Scheduled Reminder"
        verbose_name_plural = "Scheduled Reminders"
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.reminder_type} for {self.appointment_id} [{self.status}]"
