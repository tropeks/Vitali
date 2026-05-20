from django.urls import path

from .views import SuggestSlotsView

urlpatterns = [
    path(
        "scheduling/suggest/",
        SuggestSlotsView.as_view(),
        name="smart-scheduling-suggest",
    ),
]
