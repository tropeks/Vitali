"""
Concrete TriageProvider — apps.triage's implementation of the apps.core port.

Registered into ``apps.core.triage_bridge`` by ``TriageConfig.ready()`` so
conversation channels (apps.whatsapp) can drive the TriageSession FSM without
importing this domain app directly (import-linter domain-independence
contract, P1-01).
"""

from __future__ import annotations

from typing import Any


class TriageSessionProvider:
    """Adapter exposing TriageSession lifecycle operations to other domains."""

    def create_session(self, *, patient: Any, contact_phone: str) -> Any:
        from apps.triage.models import TriageSession

        return TriageSession.objects.create(
            patient=patient,
            contact_phone=contact_phone,
        )

    def get_session(self, session_id: Any) -> Any | None:
        from django.core.exceptions import ValidationError

        from apps.triage.models import TriageSession

        try:
            return TriageSession.objects.get(pk=session_id)
        except (TriageSession.DoesNotExist, ValueError, ValidationError):
            return None

    def notify_emergency(self, session: Any) -> None:
        from apps.triage.services.notifications import notify_staff_emergency

        notify_staff_emergency(session)
