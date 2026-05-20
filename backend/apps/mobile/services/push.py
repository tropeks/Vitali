"""
Mobile push notification dispatcher.

`MobilePushService` is the indirection layer between the application
(callers anywhere can ask "notify user X") and the actual FCM / APNS /
web-push transports. The dispatcher always records a `PushDelivery` row
per attempt — even when no provider is configured — so the audit trail is
complete from day one.

To plug a real provider in later:

1. Implement `PushAdapter` from `apps.mobile.services.adapter_protocol`.
2. `MobilePushService.set_adapter(YourFirebaseAdapter())` at app startup
   (or via Django setting `MOBILE_PUSH_ADAPTER`).
3. The REST surface stays unchanged; existing tests continue to pass
   because they assert against the `PushDelivery` rows, not the
   underlying transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from apps.core.models import User

from ..models import MobileDevice, PushDelivery


@dataclass
class PushResult:
    delivered: int
    failed: int
    no_provider: int
    delivery_ids: list[str]


class PushAdapter(Protocol):
    def send(
        self, *, device: MobileDevice, title: str, body: str, data: dict[str, Any]
    ) -> tuple[bool, str, str]:
        """
        Send one push.

        Returns `(success, provider_message_id, provider_error)`.
        - `success=True` → message accepted by FCM/APNS (not yet delivered).
        - `success=False` → message rejected; `provider_error` carries the
          reason.
        """


class _NoProviderAdapter:
    """Default adapter — records every dispatch as `status=no_provider`."""

    def send(
        self, *, device: MobileDevice, title: str, body: str, data: dict[str, Any]
    ) -> tuple[bool, str, str]:
        # Intentionally a no-op. Returning False so the dispatcher records
        # `status=no_provider` (handled in MobilePushService.send_to_user).
        _ = (device, title, body, data)
        return False, "", "no push provider configured"


class MobilePushService:
    """Module-level singleton dispatcher. Pluggable via `set_adapter`."""

    _adapter: PushAdapter = _NoProviderAdapter()

    @classmethod
    def set_adapter(cls, adapter: PushAdapter) -> None:
        cls._adapter = adapter

    @classmethod
    def reset_adapter(cls) -> None:
        cls._adapter = _NoProviderAdapter()

    @classmethod
    def send_to_user(
        cls,
        user: User,
        *,
        title: str,
        body: str = "",
        data: dict[str, Any] | None = None,
    ) -> PushResult:
        """Send a push to every active device the user has registered."""
        payload = data or {}
        result = PushResult(delivered=0, failed=0, no_provider=0, delivery_ids=[])
        devices = list(MobileDevice.objects.filter(user=user, is_active=True))
        for device in devices:
            success, msg_id, err = cls._adapter.send(
                device=device, title=title, body=body, data=payload
            )
            if isinstance(cls._adapter, _NoProviderAdapter):
                status_value = PushDelivery.STATUS_NO_PROVIDER
                result.no_provider += 1
            elif success:
                status_value = PushDelivery.STATUS_SENT
                result.delivered += 1
            else:
                status_value = PushDelivery.STATUS_FAILED
                result.failed += 1
            delivery = PushDelivery.objects.create(
                device=device,
                user=user,
                title=title,
                body=body,
                data=payload,
                status=status_value,
                provider_message_id=msg_id,
                provider_error=err,
            )
            result.delivery_ids.append(str(delivery.id))
        return result
