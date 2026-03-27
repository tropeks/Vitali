"""
Vitali — Analytics API Views
Read-only aggregate endpoints for the KPI dashboard.
"""
from datetime import date, timedelta

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.emr.models import Appointment, Encounter, Patient, Professional


def _today():
    return timezone.localdate()


def _month_start():
    d = _today()
    return d.replace(day=1)


class OverviewView(APIView):
    """GET /api/v1/analytics/overview/ — today's and month-to-date KPIs."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = _today()
        month_start = _month_start()

        # ── Today ────────────────────────────────────────────────────────────
        today_qs = Appointment.objects.filter(start_time__date=today)
        today_data = today_qs.aggregate(
            appointments_total=Count("id"),
            appointments_completed=Count("id", filter=Q(status="completed")),
            appointments_waiting=Count("id", filter=Q(status="waiting")),
            appointments_cancelled=Count("id", filter=Q(status="cancelled")),
        )
        new_patients_today = Patient.objects.filter(created_at__date=today).count()
        encounters_today = Encounter.objects.filter(encounter_date=today)
        encounters_open = encounters_today.filter(status="open").count()
        encounters_signed = encounters_today.filter(status="signed").count()

        # ── Month ─────────────────────────────────────────────────────────────
        month_appts = Appointment.objects.filter(start_time__date__gte=month_start)
        month_totals = month_appts.aggregate(
            appointments_total=Count("id"),
            appointments_cancelled=Count("id", filter=Q(status="cancelled")),
        )
        month_total = month_totals["appointments_total"] or 0
        month_cancelled = month_totals["appointments_cancelled"] or 0
        cancellation_rate = (
            round((month_cancelled / month_total) * 100, 1) if month_total else 0.0
        )
        new_patients_month = Patient.objects.filter(
            created_at__date__gte=month_start
        ).count()
        encounters_signed_month = Encounter.objects.filter(
            encounter_date__gte=month_start, status="signed"
        ).count()

        return Response(
            {
                "today": {
                    "appointments_total": today_data["appointments_total"] or 0,
                    "appointments_completed": today_data["appointments_completed"] or 0,
                    "appointments_waiting": today_data["appointments_waiting"] or 0,
                    "appointments_cancelled": today_data["appointments_cancelled"] or 0,
                    "new_patients": new_patients_today,
                    "encounters_open": encounters_open,
                    "encounters_signed": encounters_signed,
                },
                "month": {
                    "appointments_total": month_total,
                    "new_patients": new_patients_month,
                    "encounters_signed": encounters_signed_month,
                    "cancellation_rate": cancellation_rate,
                },
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
                    "name": p.user.get_full_name() or p.user.email,
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
