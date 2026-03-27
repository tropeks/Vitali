from django.urls import path

from .views import (
    AppointmentsByDayView,
    AppointmentsByStatusView,
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
]
