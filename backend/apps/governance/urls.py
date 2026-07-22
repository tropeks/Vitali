from rest_framework.routers import DefaultRouter

from .views import ApprovalRequestViewSet

router = DefaultRouter()
router.register("governance/approvals", ApprovalRequestViewSet)

urlpatterns = router.urls
