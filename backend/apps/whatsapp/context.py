"""
ConversationContext — TypedDict accessor for ConversationSession.context JSONField.

Using a TypedDict prevents silent typo bugs (e.g. 'speciality_id' vs 'specialty_id')
that would only surface at booking-time when the slot lookup returns nothing.
"""

from typing_extensions import TypedDict


class ConversationContext(TypedDict, total=False):
    # Scheduling flow
    specialty_id: int | None
    professional_id: int | None
    date: str | None  # ISO date string "YYYY-MM-DD"
    slot_start: str | None  # ISO datetime string
    slot_end: str | None  # ISO datetime string

    # Self vs other booking
    booking_for_self: bool | None
    other_name: str | None  # Cleared after patient matched/created
    other_cpf: str | None  # Cleared immediately after patient matched/created
    other_patient_id: str | None  # UUID str — replaces other_cpf after match

    # FSM housekeeping
    mismatches: int | None  # Unrecognized input counter (FALLBACK_HUMAN at 3)
    last_message_id: str | None


_DEFAULTS: ConversationContext = {
    "specialty_id": None,
    "professional_id": None,
    "date": None,
    "slot_start": None,
    "slot_end": None,
    "booking_for_self": True,
    "other_name": None,
    "other_cpf": None,
    "other_patient_id": None,
    "mismatches": 0,
    "last_message_id": None,
}


def get_context(session) -> ConversationContext:
    """Return session.context as a ConversationContext, filling missing keys with defaults."""
    ctx = dict(_DEFAULTS)
    ctx.update(session.context or {})
    return ctx  # type: ignore[return-value]


def set_context(session, **kwargs) -> None:
    """Merge kwargs into session.context. Does NOT save — caller must call session.save()."""
    ctx = get_context(session)
    ctx.update(kwargs)
    session.context = dict(ctx)
