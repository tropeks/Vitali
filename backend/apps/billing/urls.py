"""
Billing URL configuration.
Mounted at /api/v1/billing/ from vitali/urls.py.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AsaasWebhookView,
    GlosaViewSet,
    InsuranceProviderViewSet,
    PIXChargeView,
    PriceTableViewSet,
    TISSBatchViewSet,
    TISSGuideViewSet,
    TUSSCodeViewSet,
)

router = DefaultRouter()
router.register(r"tuss", TUSSCodeViewSet, basename="tuss")
router.register(r"providers", InsuranceProviderViewSet, basename="provider")
router.register(r"price-tables", PriceTableViewSet, basename="pricetable")
router.register(r"guides", TISSGuideViewSet, basename="guide")
router.register(r"batches", TISSBatchViewSet, basename="batch")
router.register(r"glosas", GlosaViewSet, basename="glosa")

urlpatterns = [
    path("billing/", include(router.urls)),
    path("billing/pix/charges/", PIXChargeView.as_view(), name="pix-charge-create"),
    path(
        "billing/pix/charges/<uuid:charge_id>/", PIXChargeView.as_view(), name="pix-charge-detail"
    ),
    path("billing/pix/webhook/", AsaasWebhookView.as_view(), name="asaas-webhook"),
]
