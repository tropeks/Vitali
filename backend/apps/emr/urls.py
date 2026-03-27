from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    PatientViewSet, ProfessionalViewSet,
    AppointmentViewSet, ScheduleConfigViewSet,
    AvailableSlotsView, WaitingRoomView,
)

router = DefaultRouter()
router.register('patients', PatientViewSet, basename='patient')
router.register('professionals', ProfessionalViewSet, basename='professional')
router.register('appointments', AppointmentViewSet, basename='appointment')
router.register('schedule-configs', ScheduleConfigViewSet, basename='schedule-config')

urlpatterns = router.urls + [
    path('professionals/<uuid:professional_id>/available-slots', AvailableSlotsView.as_view()),
    path('waiting-room', WaitingRoomView.as_view()),
]
