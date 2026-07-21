from django.urls import path

from .views import (
    OrthancSyncTriggerView,
    OrthancWebhookView,
    StudyDetailView,
    StudyListCreateView,
    StudyOrthancBackfillView,
    ViewerAuthorizationView,
)

urlpatterns = [
    path(
        "imaging/viewer-auth/",
        ViewerAuthorizationView.as_view(),
        name="imaging-viewer-auth",
    ),
    path("imaging/studies/", StudyListCreateView.as_view(), name="imaging-study-list"),
    path(
        "imaging/orthanc/webhook/",
        OrthancWebhookView.as_view(),
        name="imaging-orthanc-webhook",
    ),
    path(
        "imaging/studies/<uuid:study_id>/",
        StudyDetailView.as_view(),
        name="imaging-study-detail",
    ),
    path(
        "imaging/studies/<uuid:study_id>/orthanc/",
        StudyOrthancBackfillView.as_view(),
        name="imaging-study-orthanc",
    ),
    path(
        "imaging/orthanc/sync/",
        OrthancSyncTriggerView.as_view(),
        name="imaging-orthanc-sync",
    ),
]
