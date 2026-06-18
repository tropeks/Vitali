from django.urls import path

from .views import (
    AccessActivateView,
    AccessDetailView,
    AccessListCreateView,
    AccessRevokeView,
    MeAllergiesView,
    MeAppointmentsView,
    MeEncountersView,
    MePrescriptionsView,
    MeView,
    MeExportView,
    MeDeletionRequestView,
)

urlpatterns = [
    path("portal/access/", AccessListCreateView.as_view(), name="portal-access-list"),
    path(
        "portal/access/activate/",
        AccessActivateView.as_view(),
        name="portal-access-activate",
    ),
    path(
        "portal/access/<uuid:access_id>/",
        AccessDetailView.as_view(),
        name="portal-access-detail",
    ),
    path(
        "portal/access/<uuid:access_id>/revoke/",
        AccessRevokeView.as_view(),
        name="portal-access-revoke",
    ),
    path("portal/me/", MeView.as_view(), name="portal-me"),
    path("portal/me/appointments/", MeAppointmentsView.as_view(), name="portal-me-appts"),
    path("portal/me/encounters/", MeEncountersView.as_view(), name="portal-me-encs"),
    path(
        "portal/me/prescriptions/",
        MePrescriptionsView.as_view(),
        name="portal-me-rx",
    ),
    path("portal/me/allergies/", MeAllergiesView.as_view(), name="portal-me-allergies"),
    path("portal/me/export/", MeExportView.as_view(), name="portal-me-export"),
    path("portal/me/delete-request/", MeDeletionRequestView.as_view(), name="portal-me-delete"),
]
