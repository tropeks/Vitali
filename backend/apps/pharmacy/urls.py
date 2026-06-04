from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AcknowledgeControlledAlertView,
    AcknowledgeStockAlertView,
    ControlledAlertsView,
    DispensationViewSet,
    DispenseView,
    DrugViewSet,
    MaterialViewSet,
    PurchaseOrderViewSet,
    StockAlertsView,
    StockAvailabilityView,
    StockItemViewSet,
    StockMovementViewSet,
    StockRiskView,
    SupplierViewSet,
)

router = DefaultRouter()
router.register(r"drugs", DrugViewSet, basename="drug")
router.register(r"materials", MaterialViewSet, basename="material")
router.register(r"stock/items", StockItemViewSet, basename="stockitem")
router.register(r"stock/movements", StockMovementViewSet, basename="stockmovement")
router.register(r"dispensations", DispensationViewSet, basename="dispensation")
router.register(r"suppliers", SupplierViewSet, basename="supplier")
router.register(r"purchase-orders", PurchaseOrderViewSet, basename="purchase-order")

urlpatterns = [
    path("pharmacy/", include(router.urls)),
    path("pharmacy/stock/alerts/", StockAlertsView.as_view(), name="stock-alerts"),
    path(
        "pharmacy/stock/availability/", StockAvailabilityView.as_view(), name="stock-availability"
    ),
    path("pharmacy/dispense/", DispenseView.as_view(), name="pharmacy-dispense"),
    # Stockout-prediction wedge S3: proactive predictive risk surface + ack.
    path("pharmacy/stock/risk/", StockRiskView.as_view(), name="stock-risk"),
    path(
        "pharmacy/stock-alerts/<uuid:alert_id>/acknowledge/",
        AcknowledgeStockAlertView.as_view(),
        name="stock-alert-acknowledge",
    ),
    # Controlled-diversion wedge C3: compliance surface + ack.
    path("pharmacy/controlled/alerts/", ControlledAlertsView.as_view(), name="controlled-alerts"),
    path(
        "pharmacy/controlled/alerts/<uuid:alert_id>/acknowledge/",
        AcknowledgeControlledAlertView.as_view(),
        name="controlled-alert-acknowledge",
    ),
]
