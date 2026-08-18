"""Onda 3 / 3.4 — DPO-facing read of the audit trail.

The immutable ``AuditLog`` (append-only, triggers block UPDATE/DELETE/TRUNCATE
— see ``apps/core/models.py``) has had no read-side consumer besides the
aggregated wedge metrics in ``views_telemetry.py``. A DPO cannot today answer
"quem abriu o prontuário do paciente X" without a database console. This adds
exactly that: a paginated, filterable, GET-only view.

Design decisions:

* **Tenant scoping** — ``AuditLog`` is a SHARED table (``schema_name`` is a
  denormalized discriminator, not an FK); every query goes through
  ``AuditLog.for_current_tenant()`` (SYS-1) so a tenant-A admin can never see
  tenant-B rows.
* **Read-only, structurally** — ``generics.ListAPIView``, not a ViewSet with
  disabled methods: there is no ``create``/``update``/``destroy`` action to
  accidentally wire up, so a future edit here cannot open a write path by
  forgetting to override a method.
* **Permission — ``IsTenantAdmin``** — reading the trail is reading metadata
  about who accessed which patient record, i.e. sensitive in its own right
  (an org chart of who's been looking at whom). It is gated the same way
  role/user administration is (``IsTenantAdmin``: tenant admin capability or
  Vitali platform operator), NOT a regular clinical permission like
  ``emr.read`` — a clinician who can read a chart should not, by that same
  permission, be able to read everyone else's access history to every chart.
* **Response shape** — see ``AuditTrailEntrySerializer``: no ``old_data``/
  ``new_data``. Those columns can carry full record snapshots; exposing them
  here would make a traceability endpoint into a PHI export bypassing
  per-module permissions.
* **``?patient=`` filter — known limitation** — ``AuditLog`` has no
  denormalized ``patient_id`` column (adding one is a model change, out of
  scope here). The filter matches ``resource_id`` directly, which covers (a)
  direct ``Patient``/chart-level access and (b) any ``list`` navigated with
  ``?patient=`` on an audited viewset (``AuditReadMixin.list`` logs the
  patient id as ``resource_id`` for exactly this reason — see mixins.py). It
  does NOT catch ``retrieve`` of one specific child record (e.g. a single
  ``Prescription``) by that record's own id — that row's ``resource_id`` is
  the prescription's id, not the patient's. Denormalizing ``patient_id`` onto
  ``AuditLog`` would close this gap; flagged as follow-up.
"""

from __future__ import annotations

from django_filters import rest_framework as django_filters
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated

from apps.core.models import AuditLog
from apps.core.permissions import IsTenantAdmin
from apps.core.serializers import AuditTrailEntrySerializer


class AuditTrailPagination(PageNumberPagination):
    page_size = 50
    max_page_size = 200
    page_size_query_param = "page_size"


class AuditTrailFilter(django_filters.FilterSet):
    patient = django_filters.CharFilter(field_name="resource_id", lookup_expr="exact")
    user = django_filters.NumberFilter(field_name="user_id", lookup_expr="exact")
    resource_type = django_filters.CharFilter(field_name="resource_type", lookup_expr="exact")
    action = django_filters.CharFilter(field_name="action", lookup_expr="exact")
    date_from = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = django_filters.DateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = AuditLog
        fields = ("patient", "user", "resource_type", "action", "date_from", "date_to")


class AuditTrailListView(generics.ListAPIView):
    """``GET /api/v1/audit-trail/`` — paginated, tenant-scoped, read-only.

    Filters: ``?patient=<id>`` ``?user=<id>`` ``?resource_type=Patient``
    ``?action=view_record`` ``?date_from=`` ``?date_to=`` (ISO 8601).
    """

    serializer_class = AuditTrailEntrySerializer
    permission_classes = [IsAuthenticated, IsTenantAdmin]
    pagination_class = AuditTrailPagination
    filter_backends = [django_filters.DjangoFilterBackend]
    filterset_class = AuditTrailFilter

    def get_queryset(self):
        return AuditLog.for_current_tenant().select_related("user").order_by("-created_at")
