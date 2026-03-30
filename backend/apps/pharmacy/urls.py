from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DrugViewSet,
    MaterialViewSet,
    StockItemViewSet,
    StockMovementViewSet,
    StockAlertsView,
    StockAvailabilityView,
    DispensationViewSet,
    DispenseView,
)

router = DefaultRouter()
router.register(r'drugs', DrugViewSet, basename='drug')
router.register(r'materials', MaterialViewSet, basename='material')
router.register(r'stock/items', StockItemViewSet, basename='stockitem')
router.register(r'stock/movements', StockMovementViewSet, basename='stockmovement')
router.register(r'dispensations', DispensationViewSet, basename='dispensation')

urlpatterns = [
    path('pharmacy/', include(router.urls)),
    path('pharmacy/stock/alerts/', StockAlertsView.as_view(), name='stock-alerts'),
    path('pharmacy/stock/availability/', StockAvailabilityView.as_view(), name='stock-availability'),
    path('pharmacy/dispense/', DispenseView.as_view(), name='pharmacy-dispense'),
]
