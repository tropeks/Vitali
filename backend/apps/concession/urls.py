from rest_framework.routers import DefaultRouter

from .views_assets import (
    AssetMovementViewSet,
    EquipmentAssetViewSet,
    MaintenanceTicketViewSet,
)
from .views_contract import (
    ConcessionContractViewSet,
    ContractServicePriceViewSet,
    ServiceRecipeViewSet,
)
from .views_logistics import (
    DispatchViewSet,
    PickListViewSet,
    ProofOfDeliveryViewSet,
    SupplyRequisitionViewSet,
)

router = DefaultRouter()
# C1 — Frota em comodato
router.register("concession/assets", EquipmentAssetViewSet, basename="concession-asset")
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

urlpatterns = router.urls
