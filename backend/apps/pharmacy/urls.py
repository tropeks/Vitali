from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AcknowledgeControlledAlertView,
    AcknowledgeStockAlertView,
    AllergenClassViewSet,
    ControlledAlertsView,
    CurationReadinessView,
    DispensationViewSet,
    DispenseView,
    DoseRuleViewSet,
    DrugInteractionViewSet,
    DrugViewSet,
    FormularyUploadCommitView,
    FormularyUploadPreviewView,
    InventoryCountViewSet,
    LotRecallViewSet,
    MaterialViewSet,
    PharmacistValidationViewSet,
    PurchaseOrderViewSet,
    StockAlertsView,
    StockAvailabilityView,
    StockItemViewSet,
    StockMovementViewSet,
    StockRiskView,
    StockTransferViewSet,
    StorageLocationViewSet,
    SupplierContractViewSet,
    SupplierInvoiceViewSet,
    SupplierViewSet,
    ThreeWayMatchViewSet,
    WarehouseViewSet,
)

router = DefaultRouter()
router.register(r"drugs", DrugViewSet, basename="drug")
router.register(r"materials", MaterialViewSet, basename="material")
router.register(r"dose-rules", DoseRuleViewSet, basename="dose-rule")
router.register(r"allergen-classes", AllergenClassViewSet, basename="allergen-class")
router.register(r"drug-interactions", DrugInteractionViewSet, basename="drug-interaction")
router.register(r"stock/items", StockItemViewSet, basename="stockitem")
router.register(r"stock/movements", StockMovementViewSet, basename="stockmovement")
router.register(r"dispensations", DispensationViewSet, basename="dispensation")
router.register(r"suppliers", SupplierViewSet, basename="supplier")
router.register(r"purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register(r"supplier-contracts", SupplierContractViewSet, basename="supplier-contract")
router.register(r"supplier-invoices", SupplierInvoiceViewSet, basename="supplier-invoice")
router.register(r"three-way-matches", ThreeWayMatchViewSet, basename="three-way-match")
router.register(r"warehouses", WarehouseViewSet, basename="warehouse")
router.register(r"storage-locations", StorageLocationViewSet, basename="storage-location")
router.register(r"inventory-counts", InventoryCountViewSet, basename="inventory-count")
router.register(r"stock/transfers", StockTransferViewSet, basename="stock-transfer")
router.register(r"stock/recalls", LotRecallViewSet, basename="lot-recall")
router.register(
    r"clinical-validations", PharmacistValidationViewSet, basename="clinical-validation"
)

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
    # S29-05: Curation readiness dashboard.
    path(
        "pharmacy/curation/readiness/",
        CurationReadinessView.as_view(),
        name="curation-readiness",
    ),
    # D-T1: pharmacist-facing formulary CSV upload (preview + commit).
    path(
        "pharmacy/formulary/upload/preview/",
        FormularyUploadPreviewView.as_view(),
        name="formulary-upload-preview",
    ),
    path(
        "pharmacy/formulary/upload/commit/",
        FormularyUploadCommitView.as_view(),
        name="formulary-upload-commit",
    ),
    # Controlled-diversion wedge C3: compliance surface + ack.
    path("pharmacy/controlled/alerts/", ControlledAlertsView.as_view(), name="controlled-alerts"),
    path(
        "pharmacy/controlled/alerts/<uuid:alert_id>/acknowledge/",
        AcknowledgeControlledAlertView.as_view(),
        name="controlled-alert-acknowledge",
    ),
]
