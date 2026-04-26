"""URL routing for the HR app."""

from rest_framework.routers import DefaultRouter

from .views import EmployeeViewSet

router = DefaultRouter()
router.register(r"hr/employees", EmployeeViewSet, basename="employee")

urlpatterns = router.urls
