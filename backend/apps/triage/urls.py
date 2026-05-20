from django.urls import path

from .views import (
    QuestionBankView,
    SessionAnswerView,
    SessionCancelView,
    SessionChiefComplaintView,
    SessionCompleteView,
    SessionDetailView,
    SessionEvaluateView,
    SessionListCreateView,
)

urlpatterns = [
    path("triage/questions/", QuestionBankView.as_view(), name="triage-questions"),
    path("triage/sessions/", SessionListCreateView.as_view(), name="triage-session-list"),
    path(
        "triage/sessions/<uuid:session_id>/",
        SessionDetailView.as_view(),
        name="triage-session-detail",
    ),
    path(
        "triage/sessions/<uuid:session_id>/complaint/",
        SessionChiefComplaintView.as_view(),
        name="triage-session-complaint",
    ),
    path(
        "triage/sessions/<uuid:session_id>/answer/",
        SessionAnswerView.as_view(),
        name="triage-session-answer",
    ),
    path(
        "triage/sessions/<uuid:session_id>/evaluate/",
        SessionEvaluateView.as_view(),
        name="triage-session-evaluate",
    ),
    path(
        "triage/sessions/<uuid:session_id>/complete/",
        SessionCompleteView.as_view(),
        name="triage-session-complete",
    ),
    path(
        "triage/sessions/<uuid:session_id>/cancel/",
        SessionCancelView.as_view(),
        name="triage-session-cancel",
    ),
]
