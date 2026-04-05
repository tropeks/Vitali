"""
S-055/S-056: PIX payment signals.

appointment_paid: fired by the Asaas webhook handler when a PIX charge
  transitions to PAID. Triggers the appointment confirmation email (S-056)
  via Celery — never inline to avoid rolling back the webhook transaction.
"""
from django.dispatch import Signal

# Signal args: sender=PIXCharge, appointment=Appointment instance
appointment_paid = Signal()
