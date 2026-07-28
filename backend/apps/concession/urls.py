from rest_framework.routers import DefaultRouter

from .views_assets import (
    AssetMovementViewSet,
    AssetServiceViewSet,
    EquipmentAssetViewSet,
    MaintenanceTicketViewSet,
)
from .views_catalog import ConcessionServiceViewSet
from .views_contract import (
    ConcessionContractViewSet,
    ContractServicePriceViewSet,
    ServiceRecipeViewSet,
)
from .views_logistics import (
    DispatchDiscrepancyViewSet,
    DispatchViewSet,
    PickListViewSet,
    ProofOfDeliveryViewSet,
    SupplyRequisitionViewSet,
)
from .views_pnl import (
    ContractPnlViewSet,
    ExamConsumptionViewSet,
    MaterialUnitCostViewSet,
)

router = DefaultRouter()
# B0 — Catálogo de serviços/exames
router.register("concession/services", ConcessionServiceViewSet, basename="concession-service")
# C1 — Frota em comodato
router.register("concession/assets", EquipmentAssetViewSet, basename="concession-asset")
router.register(
    "concession/asset-services", AssetServiceViewSet, basename="concession-asset-service"
)
router.register(
    "concession/asset-movements", AssetMovementViewSet, basename="concession-asset-movement"
)
router.register(
    "concession/maintenance-tickets",
    MaintenanceTicketViewSet,
    basename="concession-maintenance-ticket",
)
# C2 — Contrato + preço + recipe
router.register("concession-contracts", ConcessionContractViewSet, basename="concession-contract")
router.register("contract-prices", ContractServicePriceViewSet, basename="contract-price")
router.register("service-recipes", ServiceRecipeViewSet, basename="service-recipe")
# C3 — Logística de reposição
router.register(
    "concession/supply-requisitions", SupplyRequisitionViewSet, basename="supply-requisition"
)
router.register("concession/pick-lists", PickListViewSet, basename="pick-list")
router.register("concession/dispatches", DispatchViewSet, basename="dispatch")
router.register(
    "concession/proof-of-deliveries", ProofOfDeliveryViewSet, basename="proof-of-delivery"
)
router.register(
    "concession/dispatch-discrepancies",
    DispatchDiscrepancyViewSet,
    basename="concession-dispatch-discrepancy",
)
# C4 — P&L do contrato + custo de insumo + ledger de consumo
router.register(
    "concession/material-unit-costs",
    MaterialUnitCostViewSet,
    basename="concession-material-unit-cost",
)
router.register(
    "concession/exam-consumptions",
    ExamConsumptionViewSet,
    basename="concession-exam-consumption",
)
router.register("concession/contracts", ContractPnlViewSet, basename="concession-contract-pnl")

urlpatterns = router.urls
