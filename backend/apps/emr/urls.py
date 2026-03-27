from rest_framework.routers import DefaultRouter
from .views import PatientViewSet, ProfessionalViewSet

router = DefaultRouter()
router.register('patients', PatientViewSet, basename='patient')
router.register('professionals', ProfessionalViewSet, basename='professional')

urlpatterns = router.urls
