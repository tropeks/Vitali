from django.urls import path

from .views import DrugForecastView

urlpatterns = [
    path("pharmacy/forecast/", DrugForecastView.as_view(), name="pharmacy-ai-forecast"),
]
