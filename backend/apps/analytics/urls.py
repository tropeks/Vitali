from django.urls import path

from .views import (
    AppointmentsByDayView,
    AppointmentsByStatusView,
    BatchThroughputView,
    BillingOverviewView,
    DenialByInsurerView,
    GlosaAccuracyView,
    MonthlyRevenueView,
    OverviewView,
    PatientsByMonthView,
    TopProfessionalsView,
    WaitingTimeView,
)

urlpatterns = [
    path("overview/", OverviewView.as_view(), name="analytics-overview"),
    path("appointments-by-day/", AppointmentsByDayView.as_view(), name="analytics-appts-by-day"),
    path("appointments-by-status/", AppointmentsByStatusView.as_view(), name="analytics-appts-by-status"),
    path("patients-by-month/", PatientsByMonthView.as_view(), name="analytics-patients-by-month"),
    path("top-professionals/", TopProfessionalsView.as_view(), name="analytics-top-professionals"),
    path("waiting-time/", WaitingTimeView.as_view(), name="analytics-waiting-time"),
    # Billing analytics (S-035)
    path("billing/overview/", BillingOverviewView.as_view(), name="analytics-billing-overview"),
    path("billing/monthly-revenue/", MonthlyRevenueView.as_view(), name="analytics-billing-monthly-revenue"),
    path("billing/denial-by-insurer/", DenialByInsurerView.as_view(), name="analytics-billing-denial-by-insurer"),
    path("billing/batch-throughput/", BatchThroughputView.as_view(), name="analytics-billing-batch-throughput"),
    path("billing/glosa-accuracy/", GlosaAccuracyView.as_view(), name="analytics-billing-glosa-accuracy"),
]
