"""Reusable DRF view mixins."""

import logging

from apps.core.models import AuditLog

logger = logging.getLogger(__name__)


class AuditReadMixin:
    """Log read access (``retrieve``) of a record to the immutable AuditLog as a
    ``view_record`` action — CFM Res. 1.821/2007 requires traceability of access
    to clinical records, not just changes.

    Only single-record reads (``retrieve``) are logged, never ``list``, to keep
    the trail meaningful and avoid one row per result. Set ``audit_resource_type``
    on the viewset to the name recorded in the trail (e.g. "Patient", "Encounter").
    """

    audit_resource_type: str | None = None

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        if 200 <= response.status_code < 300:
            lookup = self.lookup_url_kwarg or self.lookup_field
            self._log_view_record(request, kwargs.get(lookup))
        return response

    def _log_view_record(self, request, resource_id):
        try:
            user = request.user if getattr(request.user, "is_authenticated", False) else None
            AuditLog.objects.create(
                user=user,
                action="view_record",
                resource_type=self.audit_resource_type or self.__class__.__name__,
                resource_id=str(resource_id or ""),
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:2000],
            )
        except Exception:  # noqa: BLE001 — audit logging must never break a read
            logger.warning("view_record audit failed", exc_info=True)
