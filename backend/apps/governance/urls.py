from rest_framework.routers import DefaultRouter

from .views import ApprovalRequestViewSet, DomainEventOutboxViewSet, IntegrationInboxViewSet

router = DefaultRouter()
router.register("governance/approvals", ApprovalRequestViewSet)
router.register("governance/integration-inbox", IntegrationInboxViewSet)
router.register("governance/integration-outbox", DomainEventOutboxViewSet)

urlpatterns = router.urls
