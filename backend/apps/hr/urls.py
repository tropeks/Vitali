"""URL routing for the HR app."""

from rest_framework.routers import DefaultRouter

from .views import (
    EmployeeViewSet,
    OccupationalHealthExamViewSet,
    TimeEntryViewSet,
    WorkScheduleViewSet,
)

router = DefaultRouter()
router.register(r"hr/employees", EmployeeViewSet, basename="employee")
router.register(r"hr/work-schedules", WorkScheduleViewSet, basename="work-schedule")
router.register(r"hr/time-entries", TimeEntryViewSet, basename="time-entry")
router.register(
    r"hr/occupational-health-exams", OccupationalHealthExamViewSet, basename="health-exam"
)

urlpatterns = router.urls
