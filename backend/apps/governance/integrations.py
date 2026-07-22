"""Protocol-neutral integration handler registry.

Protocol adapters normalize messages before calling InboxService.receive().
Domain modules register handlers here without coupling governance to HL7/DICOM/etc.
"""

from collections.abc import Callable

InboxHandler = Callable[[dict, dict], None]
OutboxHandler = Callable[[object], None]

_inbox_handlers: dict[str, InboxHandler] = {}
_outbox_handlers: dict[str, list[OutboxHandler]] = {}


def register_inbox_handler(message_type: str, handler: InboxHandler) -> None:
    _inbox_handlers[message_type] = handler


def register_outbox_handler(event_type: str, handler: OutboxHandler) -> None:
    _outbox_handlers.setdefault(event_type, []).append(handler)


def handle_inbox(message_type: str, payload: dict, headers: dict) -> None:
    handler = _inbox_handlers.get(message_type)
    if handler is None:
        raise LookupError(f"Nenhum handler registrado para {message_type}.")
    handler(payload, headers)


def publish_outbox(event) -> None:
    handlers = _outbox_handlers.get(event.event_type, ())
    if not handlers:
        raise LookupError(f"Nenhum publisher registrado para {event.event_type}.")
    for handler in handlers:
        handler(event)
