from django.urls import path

from .views import SignatureCreateView, SignatureListView

urlpatterns = [
    path("signatures/sign/", SignatureCreateView.as_view(), name="signatures-sign"),
    path("signatures/", SignatureListView.as_view(), name="signatures-list"),
]
