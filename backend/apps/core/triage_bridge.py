"""
Triage provider registry — the apps.core port between conversation channels
(e.g. apps.whatsapp) and the triage domain (apps.triage).

Domain apps must not import each other directly (import-linter
domain-independence contract, P1-01). This module is the dependency-inversion
seam that lets the WhatsApp inbound FSM drive a symptom triage without a
static ``apps.whatsapp -> apps.triage`` import:

- apps.core defines the port (this module) and imports NO domain app.
- apps.triage registers its concrete provider here in ``TriageConfig.ready()``.
- apps.whatsapp resolves the provider at call time via
  ``get_triage_provider()`` and drives the returned session objects purely by
  duck typing (``record_chief_complaint``, ``answer``, ``evaluate_now``, ...).

If the triage app is not installed (or has not registered), consumers get
``None`` and must degrade gracefully (WhatsApp answers with the
"triage disabled" message).
"""

from __future__ import annotations

from typing import Any, Protocol


class TriageProvider(Protocol):
    """Operations conversation channels need from the triage domain.

    Session objects returned by ``create_session``/``get_session`` are opaque
    to callers: they expose the TriageSession FSM surface
    (``record_chief_complaint(text)``, ``answer(key, value)``,
    ``next_question_key``, ``current_question()``, ``evaluate_now()``,
    ``cancel()``, ``urgency``, ``id``) but callers must not assume a concrete
    model class.
    """

    def create_session(self, *, patient: Any, contact_phone: str) -> Any:
        """Create and persist a new triage session."""
        ...

    def get_session(self, session_id: Any) -> Any | None:
        """Return the session for ``session_id``, or None if missing/invalid."""
        ...

    def notify_emergency(self, session: Any) -> None:
        """Page configured staff about an emergency classification. Never raises."""
        ...


_provider: TriageProvider | None = None


def register_triage_provider(provider: TriageProvider) -> None:
    """Register the active triage provider (called by TriageConfig.ready())."""
    global _provider
    _provider = provider


def get_triage_provider() -> TriageProvider | None:
    """Return the registered triage provider, or None if triage is unavailable."""
    return _provider
