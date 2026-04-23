"""
Vitali — Analytics API Views
Read-only aggregate endpoints for the KPI dashboard and billing intelligence.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.billing.models import InsuranceProvider, TISSBatch, TISSGuide
from apps.core.permissions import ModuleRequiredPermission
from apps.emr.models import Appointment, Encounter, Patient, Professional

_BILLING_MODULE = ModuleRequiredPermission("billing")


def _today():
    return timezone.localdate()


def _month_start():
    d = _today()
    return d.replace(day=1)


class OverviewView(APIView):
    """GET /api/v1/analytics/overview/?period=today|week|month

    Returns clinic KPIs for the requested period.  Defaults to ``month``.
    Revenue (sum of paid TISS guide values) is included when billing data exists.
    """

    permission_classes = [IsAuthenticated]

    _VALID_PERIODS = {"today", "week", "month"}

    def _period_start(self, period: str):
        today = _today()
        if period == "today":
            return today
        if period == "week":
            # Monday of the current week
            return today - timedelta(days=today.weekday())
        return _month_start()

    def get(self, request):
        period = request.query_params.get("period", "month")
        if period not in self._VALID_PERIODS:
            period = "month"

        today = _today()
        since = self._period_start(period)

        appts = Appointment.objects.filter(start_time__date__gte=since)
        if period == "today":
            appts = Appointment.objects.filter(start_time__date=today)

        appt_agg = appts.aggregate(
            appointments_total=Count("id"),
            appointments_completed=Count("id", filter=Q(status="completed")),
            appointments_confirmed=Count("id", filter=Q(status="confirmed")),
            appointments_waiting=Count("id", filter=Q(status="waiting")),
            appointments_cancelled=Count("id", filter=Q(status="cancelled")),
            appointments_no_show=Count("id", filter=Q(status="no_show")),
        )
        total = appt_agg["appointments_total"] or 0
        cancelled = appt_agg["appointments_cancelled"] or 0
        no_show = appt_agg["appointments_no_show"] or 0
        confirmed = appt_agg["appointments_confirmed"] or 0
        cancellation_rate = round((cancelled / total) * 100, 1) if total else 0.0
        # no_show_rate denominator follows plan spec: confirmed OR 1 to avoid div-by-zero
        no_show_rate = round((no_show / (confirmed or 1)) * 100, 1) if confirmed else 0.0

        new_patients = Patient.objects.filter(created_at__date__gte=since).count()
        if period == "today":
            new_patients = Patient.objects.filter(created_at__date=today).count()

        encounters_qs = Encounter.objects.filter(encounter_date__date__gte=since)
        if period == "today":
            encounters_qs = Encounter.objects.filter(encounter_date__date=today)
        enc_agg = encounters_qs.aggregate(
            open=Count("id", filter=Q(status="open")),
            signed=Count("id", filter=Q(status="signed")),
        )
        encounters_open = enc_agg["open"] or 0
        encounters_signed = enc_agg["signed"] or 0

        # Revenue: sum of paid TISS guide values for the period (billing optional).
        revenue = Decimal("0.00")
        try:
            rev_agg = TISSGuide.objects.filter(
                status="paid",
                created_at__date__gte=since,
            ).aggregate(total=Sum("total_value"))
            revenue = rev_agg["total"] or Decimal("0.00")
        except Exception:
            pass

        # Wait time: average minutes between arrived_at and started_at for the period
        wait_expr = ExpressionWrapper(
            F("started_at") - F("arrived_at"),
            output_field=DurationField(),
        )
        wait_qs = (
            appts.filter(
                arrived_at__isnull=False,
                started_at__isnull=False,
                started_at__gte=F("arrived_at"),
            )
            .annotate(wait=wait_expr)
            .aggregate(avg=Avg("wait"))
        )
        wait_avg = wait_qs["avg"]
        wait_time_avg_min = round(wait_avg.total_seconds() / 60, 1) if wait_avg else None

        return Response(
            {
                "period": period,
                "since": since.isoformat(),
                "appointments_total": total,
                "appointments_completed": appt_agg["appointments_completed"] or 0,
                "appointments_confirmed": confirmed,
                "appointments_waiting": appt_agg["appointments_waiting"] or 0,
                "appointments_cancelled": cancelled,
                "appointments_no_show": no_show,
                "cancellation_rate": cancellation_rate,
                "no_show_rate": no_show_rate,
                "new_patients": new_patients,
                "encounters_open": encounters_open,
                "encounters_signed": encounters_signed,
                "revenue": revenue,
                "wait_time_avg_min": wait_time_avg_min,
            }
        )


class AppointmentsByDayView(APIView):
    """GET /api/v1/analytics/appointments-by-day/?days=30"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        days = min(int(request.query_params.get("days", 30)), 365)
        since = _today() - timedelta(days=days - 1)

        rows = (
            Appointment.objects.filter(start_time__date__gte=since)
            .annotate(day=TruncDate("start_time"))
            .values("day")
            .annotate(
                total=Count("id"),
                completed=Count("id", filter=Q(status="completed")),
                cancelled=Count("id", filter=Q(status="cancelled")),
            )
            .order_by("day")
        )

        # Fill in zero-count days so the chart has continuous data
        by_day = {r["day"]: r for r in rows}
        result = []
        for i in range(days):
            d = since + timedelta(days=i)
            row = by_day.get(d)
            result.append(
                {
                    "date": d.isoformat(),
                    "total": row["total"] if row else 0,
                    "completed": row["completed"] if row else 0,
                    "cancelled": row["cancelled"] if row else 0,
                }
            )
        return Response(result)


class AppointmentsByStatusView(APIView):
    """GET /api/v1/analytics/appointments-by-status/ — current month, grouped by status."""

    permission_classes = [IsAuthenticated]

    STATUS_LABELS = {
        "scheduled": "Agendado",
        "confirmed": "Confirmado",
        "waiting": "Aguardando",
        "in_progress": "Em atendimento",
        "completed": "Concluído",
        "cancelled": "Cancelado",
        "no_show": "Não compareceu",
    }

    def get(self, request):
        month_start = _month_start()
        rows = (
            Appointment.objects.filter(start_time__date__gte=month_start)
            .values("status")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        return Response(
            [
                {
                    "status": r["status"],
                    "label": self.STATUS_LABELS.get(r["status"], r["status"]),
                    "count": r["count"],
                }
                for r in rows
            ]
        )


class PatientsByMonthView(APIView):
    """GET /api/v1/analytics/patients-by-month/?months=6"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        months = min(int(request.query_params.get("months", 6)), 24)
        # Calculate the start of N months ago
        today = _today()
        # Go back `months` months from the start of the current month
        year = today.year
        month = today.month - months
        while month <= 0:
            month += 12
            year -= 1
        since = date(year, month, 1)

        rows = (
            Patient.objects.filter(created_at__date__gte=since)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )

        by_month = {r["month"].date().replace(day=1): r["count"] for r in rows}

        result = []
        y, m = year, month
        for _ in range(months):
            d = date(y, m, 1)
            result.append(
                {
                    "month": d.isoformat(),
                    "label": d.strftime("%b/%Y"),
                    "count": by_month.get(d, 0),
                }
            )
            m += 1
            if m > 12:
                m = 1
                y += 1

        return Response(result)


class TopProfessionalsView(APIView):
    """GET /api/v1/analytics/top-professionals/?limit=5"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = min(int(request.query_params.get("limit", 5)), 20)
        month_start = _month_start()

        rows = (
            Professional.objects.annotate(
                completed=Count(
                    "appointments",
                    filter=Q(
                        appointments__status="completed",
                        appointments__start_time__date__gte=month_start,
                    ),
                )
            )
            .select_related("user")
            .order_by("-completed")[:limit]
        )

        return Response(
            [
                {
                    "professional_id": str(p.id),
                    "name": p.user.full_name or p.user.email,
                    "specialty": p.specialty or "",
                    "completed": p.completed,
                }
                for p in rows
            ]
        )


class WaitingTimeView(APIView):
    """GET /api/v1/analytics/waiting-time/ — average wait stats this month."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Waiting time = in_progress appointments this month whose start was recorded.
        # The Appointment model doesn't store an "actual start" timestamp, so we
        # approximate using the scheduled start_time vs. the created_at delta for
        # completed same-day appointments.  If no data is available return zeros.
        month_start = _month_start()
        try:
            completed_today = Appointment.objects.filter(
                status="completed",
                start_time__date__gte=month_start,
            )
            # Proxy: difference between created_at (booking time) and start_time
            # is not meaningful for wait time.  Return placeholder zeros unless
            # real timestamps are available in a future schema iteration.
            total = completed_today.count()
            return Response(
                {
                    "average_minutes": 0,
                    "sample_size": total,
                    "note": "Tempo de espera real disponível após integração com check-in digital.",
                }
            )
        except Exception:
            return Response({"average_minutes": 0, "sample_size": 0, "note": ""})


# ─── Billing Analytics (S-035) ───────────────────────────────────────────────

# Statuses that represent guides that entered the TISS billing cycle (non-draft).
_NON_DRAFT_STATUSES = ["submitted", "paid", "denied", "appeal"]


def _months_param(request, default: int = 6) -> int:
    """Parse and clamp ?months= query param. Range: 1–24."""
    try:
        months = int(request.query_params.get("months", default))
    except (TypeError, ValueError):
        months = default
    return max(1, min(months, 24))


def _month_range_start(months: int) -> date:
    """Return the first day of the month that is `months` months ago from today."""
    today = _today()
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _competency_for_month(d: date) -> str:
    """Return competency string 'AAAA-MM' for the given date."""
    return d.strftime("%Y-%m")


class BillingOverviewView(APIView):
    """GET /api/v1/analytics/billing/overview/ — current-month KPI cards."""

    permission_classes = [IsAuthenticated, _BILLING_MODULE]

    def get(self, request):
        today = _today()
        period = _competency_for_month(today)

        qs = TISSGuide.objects.filter(competency=period)
        totals = qs.aggregate(
            total_billed=Sum("total_value"),
            total_collected=Sum("total_value", filter=Q(status="paid")),
            total_denied=Sum("total_value", filter=Q(status__in=["denied", "appeal"])),
            guides_total=Count("id"),
            guides_submitted=Count("id", filter=Q(status="submitted")),
            guides_paid=Count("id", filter=Q(status="paid")),
            guides_denied=Count("id", filter=Q(status__in=["denied", "appeal"])),
            non_draft_count=Count("id", filter=Q(status__in=_NON_DRAFT_STATUSES)),
        )

        totals["non_draft_count"] or 0
        total_denied_val = totals["total_denied"] or Decimal("0.00")
        total_billed_val = totals["total_billed"] or Decimal("0.00")
        denial_rate = (
            round(float(total_denied_val / total_billed_val), 3) if total_billed_val else 0.0
        )

        guides_total = totals["guides_total"] or 0
        guides_submitted = totals["guides_submitted"] or 0
        guides_paid = totals["guides_paid"] or 0
        guides_denied = totals["guides_denied"] or 0
        guides_draft_pending = guides_total - guides_submitted - guides_paid - guides_denied

        return Response(
            {
                "period": period,
                "total_billed": totals["total_billed"] or Decimal("0.00"),
                "total_collected": totals["total_collected"] or Decimal("0.00"),
                "total_denied": total_denied_val,
                "denial_rate": denial_rate,
                "guides_total": guides_total,
                "guides_submitted": guides_submitted,
                "guides_paid": guides_paid,
                "guides_denied": guides_denied,
                "guides_draft_pending": max(guides_draft_pending, 0),
            }
        )


class MonthlyRevenueView(APIView):
    """GET /api/v1/analytics/billing/monthly-revenue/?months=6"""

    permission_classes = [IsAuthenticated, _BILLING_MODULE]

    def get(self, request):
        months = _months_param(request)

        # Build the list of competency strings for the requested range.
        today = _today()
        competencies = []
        y, m = today.year, today.month
        for _ in range(months):
            competencies.append(f"{y:04d}-{m:02d}")
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        competencies.reverse()  # chronological order

        rows = (
            TISSGuide.objects.filter(competency__in=competencies)
            .values("competency")
            .annotate(
                billed=Sum("total_value"),
                collected=Sum("total_value", filter=Q(status="paid")),
                denied=Sum("total_value", filter=Q(status__in=["denied", "appeal"])),
            )
            .order_by("competency")
        )

        by_competency = {r["competency"]: r for r in rows}
        result = []
        for comp in competencies:
            row = by_competency.get(comp)
            result.append(
                {
                    "period": comp,
                    "billed": row["billed"] if row and row["billed"] else Decimal("0.00"),
                    "collected": row["collected"] if row and row["collected"] else Decimal("0.00"),
                    "denied": row["denied"] if row and row["denied"] else Decimal("0.00"),
                }
            )
        return Response(result)


class DenialByInsurerView(APIView):
    """GET /api/v1/analytics/billing/denial-by-insurer/?months=6
    Returns top insurers by denied value, excluding those with <10 non-draft guides.
    """

    permission_classes = [IsAuthenticated, _BILLING_MODULE]
    _VOLUME_FLOOR = 10

    def get(self, request):
        months = _months_param(request)
        since = _month_range_start(months)

        rows = (
            TISSGuide.objects.filter(created_at__date__gte=since)
            .values("provider_id", "provider__name", "provider__ans_code")
            .annotate(
                total_guides=Count("id", filter=Q(status__in=_NON_DRAFT_STATUSES)),
                denied_guides=Count("id", filter=Q(status__in=["denied", "appeal"])),
                denied_value=Sum("total_value", filter=Q(status__in=["denied", "appeal"])),
            )
            .filter(total_guides__gte=self._VOLUME_FLOOR)
            .order_by("-denied_value")
        )

        result = []
        for r in rows:
            total = r["total_guides"] or 0
            denied = r["denied_guides"] or 0
            denial_rate = round(denied / total, 3) if total else 0.0
            result.append(
                {
                    "insurer_name": r["provider__name"] or "",
                    "ans_code": r["provider__ans_code"] or "",
                    "total_guides": total,
                    "denied_guides": denied,
                    "denial_rate": denial_rate,
                    "denied_value": r["denied_value"] or Decimal("0.00"),
                }
            )
        return Response(result)


class BatchThroughputView(APIView):
    """GET /api/v1/analytics/billing/batch-throughput/?months=6
    Returns monthly batch creation and closure counts.
    Uses two separate queries to correctly attribute batches:
    created_at → creation month, closed_at → closure month.
    """

    permission_classes = [IsAuthenticated, _BILLING_MODULE]

    def get(self, request):
        months = _months_param(request)
        since = _month_range_start(months)

        # Build ordered list of month dates for the range.
        today = _today()
        month_dates = []
        y, m = today.year, today.month
        for _ in range(months):
            month_dates.append(date(y, m, 1))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        month_dates.reverse()

        # Query 1: created counts per month.
        created_qs = (
            TISSBatch.objects.filter(created_at__date__gte=since)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(created_count=Count("id"))
        )
        created_by_month = {
            r["month"].date().replace(day=1): r["created_count"] for r in created_qs
        }

        # Query 2: closed counts per month (only batches that were closed).
        closed_qs = (
            TISSBatch.objects.filter(
                closed_at__isnull=False,
                closed_at__date__gte=since,
            )
            .annotate(month=TruncMonth("closed_at"))
            .values("month")
            .annotate(closed_count=Count("id"))
        )
        closed_by_month = {r["month"].date().replace(day=1): r["closed_count"] for r in closed_qs}

        result = []
        for d in month_dates:
            result.append(
                {
                    "period": d.strftime("%Y-%m"),
                    "created_count": created_by_month.get(d, 0),
                    "closed_count": closed_by_month.get(d, 0),
                }
            )
        return Response(result)


class GlosaAccuracyView(APIView):
    """GET /api/v1/analytics/billing/glosa-accuracy/ — prediction accuracy per insurer (S-037)."""

    permission_classes = [IsAuthenticated, _BILLING_MODULE]

    def get(self, request):
        from apps.ai.models import GlosaPrediction

        rows = (
            GlosaPrediction.objects.filter(guide__isnull=False)
            .values("insurer_ans_code")
            .annotate(
                total=Count("id", filter=Q(was_denied__isnull=False)),
                predicted_high=Count("id", filter=Q(risk_level="high")),
                denied_count=Count("id", filter=Q(was_denied=True)),
                true_positives=Count("id", filter=Q(risk_level="high", was_denied=True)),
            )
            .order_by("-denied_count")
        )

        # Resolve insurer names in a single extra query.
        insurer_names = dict(InsuranceProvider.objects.values_list("ans_code", "name"))

        result = []
        for r in rows:
            predicted_high = r["predicted_high"] or 0
            was_denied = r["denied_count"] or 0
            true_pos = r["true_positives"] or 0
            precision = round(true_pos / predicted_high, 3) if predicted_high else None
            recall = round(true_pos / was_denied, 3) if was_denied else None
            ans_code = r["insurer_ans_code"]
            result.append(
                {
                    "insurer_ans_code": ans_code,
                    "insurer_name": insurer_names.get(ans_code, ans_code),
                    "total_predictions": r["total"] or 0,
                    "predicted_high": predicted_high,
                    "was_denied": was_denied,
                    "true_positives": true_pos,
                    "precision": precision,
                    "recall": recall,
                }
            )
        return Response(result)
