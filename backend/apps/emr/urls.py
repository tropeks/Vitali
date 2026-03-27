from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    PatientViewSet, ProfessionalViewSet,
    AppointmentViewSet, ScheduleConfigViewSet,
    AvailableSlotsView, WaitingRoomView,
    EncounterViewSet, SOAPNoteViewSet, VitalSignsViewSet, ClinicalDocumentViewSet,
)

router = DefaultRouter()
router.register('patients', PatientViewSet, basename='patient')
router.register('professionals', ProfessionalViewSet, basename='professional')
router.register('appointments', AppointmentViewSet, basename='appointment')
router.register('schedule-configs', ScheduleConfigViewSet, basename='schedule-config')
router.register('encounters', EncounterViewSet, basename='encounter')
router.register('soap-notes', SOAPNoteViewSet, basename='soap-note')
router.register('vital-signs', VitalSignsViewSet, basename='vital-signs')
router.register('documents', ClinicalDocumentViewSet, basename='document')

urlpatterns = router.urls + [
    path('professionals/<uuid:professional_id>/available-slots', AvailableSlotsView.as_view()),
    path('waiting-room', WaitingRoomView.as_view()),
]
