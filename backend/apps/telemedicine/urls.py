from django.urls import path

from .views import (
    SessionCancelView,
    SessionCompleteView,
    SessionDetailView,
    SessionListCreateView,
    SessionRecordingView,
    SessionStartView,
)

urlpatterns = [
    path(
        "telemedicine/sessions/",
        SessionListCreateView.as_view(),
        name="telemedicine-session-list",
    ),
    path(
        "telemedicine/sessions/<uuid:session_id>/",
        SessionDetailView.as_view(),
        name="telemedicine-session-detail",
    ),
    path(
        "telemedicine/sessions/<uuid:session_id>/start/",
        SessionStartView.as_view(),
        name="telemedicine-session-start",
    ),
    path(
        "telemedicine/sessions/<uuid:session_id>/complete/",
        SessionCompleteView.as_view(),
        name="telemedicine-session-complete",
    ),
    path(
        "telemedicine/sessions/<uuid:session_id>/cancel/",
        SessionCancelView.as_view(),
        name="telemedicine-session-cancel",
    ),
    path(
        "telemedicine/sessions/<uuid:session_id>/recording/",
        SessionRecordingView.as_view(),
        name="telemedicine-session-recording",
    ),
]
