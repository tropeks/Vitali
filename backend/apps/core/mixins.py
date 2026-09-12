"""Reusable DRF view mixins."""

import logging

from apps.core.models import AuditLog

logger = logging.getLogger(__name__)


class AuditReadMixin:
    """Log read access to the immutable AuditLog — CFM Res. 1.821/2007 requires
    traceability of access to clinical records, not just changes.

    ``retrieve`` (single-record reads) is ALWAYS logged as ``view_record``,
    carrying the resource id. Set ``audit_resource_type`` on the viewset to
    the name recorded in the trail (e.g. "Patient", "Encounter").

    ``list`` is logged as ``view_record_list`` ONLY when the request carries a
    targeted lookup (``?patient=`` or ``?search=``) — i.e. when a user is
    hunting for a specific chart rather than browsing a routine worklist.
    An unfiltered ``list`` (e.g. today's appointment board) is NOT logged:
    it would put one row in the trail per page view of a normal work screen,
    drowning the signal without adding traceability value. What's recorded is
    the search CRITERION (the patient id or the search term), never the
    result set — the trail answers "what did this user go looking for", not
    "what PHI did the response contain" (see AuditTrailViewSet in
    views_audit.py for why the response side matters: it must not itself leak
    ``old_data``/``new_data``).
    """

    audit_resource_type: str | None = None

    #: Query params whose presence turns a ``list`` into a targeted lookup.
    AUDIT_LIST_PARAMS = ("patient", "search")

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        if 200 <= response.status_code < 300:
            lookup = self.lookup_url_kwarg or self.lookup_field
            self._log_audit_event(request, "view_record", kwargs.get(lookup))
        return response

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if 200 <= response.status_code < 300:
            criteria = {
                param: request.query_params[param]
                for param in self.AUDIT_LIST_PARAMS
                if request.query_params.get(param)
            }
            if criteria:
                self._log_audit_event(
                    request, "view_record_list", criteria.get("patient", ""), new_data=criteria
                )
        return response

    def _log_audit_event(self, request, action, resource_id, new_data=None):
        try:
            user = request.user if getattr(request.user, "is_authenticated", False) else None
            AuditLog.objects.create(
                user=user,
                action=action,
                resource_type=self.audit_resource_type or self.__class__.__name__,
                resource_id=str(resource_id or ""),
                new_data=new_data,
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:2000],
            )
        except Exception:  # noqa: BLE001 — audit logging must never break a read
            logger.warning("%s audit failed", action, exc_info=True)
