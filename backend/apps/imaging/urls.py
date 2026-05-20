from django.urls import path

from .views import StudyDetailView, StudyListCreateView, StudyOrthancBackfillView

urlpatterns = [
    path("imaging/studies/", StudyListCreateView.as_view(), name="imaging-study-list"),
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
]
