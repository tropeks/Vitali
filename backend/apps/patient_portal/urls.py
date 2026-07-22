from django.urls import path

from .views import (
    AccessActivateView,
    AccessDetailView,
    AccessListCreateView,
    AccessRevokeView,
    MeAllergiesView,
    MeAppointmentsView,
    MeConsentRevokeView,
    MeConsentsView,
    MeDeletionRequestView,
    MeEncountersView,
    MeExportView,
    MePrescriptionsView,
    MeRepresentativesView,
    MeView,
)
from .views_imaging import (
    MeImagingReportView,
    MeImagingStudiesView,
    MeImagingStudyAuthorizationView,
    MeImagingViewerAuthorizationView,
)
from .views_lab import MeLabReportPDFView, MeLabResultsView

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
    path(
        "portal/me/representatives/",
        MeRepresentativesView.as_view(),
        name="portal-me-representatives",
    ),
    path("portal/me/consents/", MeConsentsView.as_view(), name="portal-me-consents"),
    path(
        "portal/me/consents/<int:consent_id>/revoke/",
        MeConsentRevokeView.as_view(),
        name="portal-me-consent-revoke",
    ),
    path("portal/me/appointments/", MeAppointmentsView.as_view(), name="portal-me-appts"),
    path("portal/me/encounters/", MeEncountersView.as_view(), name="portal-me-encs"),
    path(
        "portal/me/prescriptions/",
        MePrescriptionsView.as_view(),
        name="portal-me-rx",
    ),
    path("portal/me/allergies/", MeAllergiesView.as_view(), name="portal-me-allergies"),
    path("portal/me/lab-results/", MeLabResultsView.as_view(), name="portal-me-lab-results"),
    path(
        "portal/me/imaging-studies/",
        MeImagingStudiesView.as_view(),
        name="portal-me-imaging-studies",
    ),
    path(
        "portal/me/imaging-studies/<uuid:study_id>/authorize/",
        MeImagingStudyAuthorizationView.as_view(),
        name="portal-me-imaging-authorize",
    ),
    path(
        "portal/me/imaging-viewer-auth/",
        MeImagingViewerAuthorizationView.as_view(),
        name="portal-me-imaging-viewer-auth",
    ),
    path(
        "portal/me/imaging-studies/<uuid:study_id>/report/",
        MeImagingReportView.as_view(),
        name="portal-me-imaging-report",
    ),
    path(
        "portal/me/lab-results/<uuid:order_id>/report/",
        MeLabReportPDFView.as_view(),
        name="portal-me-lab-report",
    ),
    path("portal/me/export/", MeExportView.as_view(), name="portal-me-export"),
    path("portal/me/delete-request/", MeDeletionRequestView.as_view(), name="portal-me-delete"),
]
