from rest_framework.routers import DefaultRouter

from .views import CostCenterViewSet, FacilityViewSet, LegalEntityViewSet, OrganizationalUnitViewSet

router = DefaultRouter()
router.register("organization/legal-entities", LegalEntityViewSet)
router.register("organization/facilities", FacilityViewSet)
router.register("organization/units", OrganizationalUnitViewSet)
router.register("organization/cost-centers", CostCenterViewSet)

urlpatterns = router.urls
