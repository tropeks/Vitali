"""URL routing for the HR app."""

from rest_framework.routers import DefaultRouter

from .views import (
    DependentViewSet,
    DutyRosterViewSet,
    EmployeeAssignmentViewSet,
    EmployeeViewSet,
    LeaveRequestViewSet,
    OccupationalHealthExamViewSet,
    PositionViewSet,
    RosterSlotViewSet,
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
# M2-S2 — RH operacional
router.register(r"hr/positions", PositionViewSet, basename="position")
router.register(r"hr/assignments", EmployeeAssignmentViewSet, basename="assignment")
router.register(r"hr/dependents", DependentViewSet, basename="dependent")
router.register(r"hr/leave-requests", LeaveRequestViewSet, basename="leave-request")
router.register(r"hr/duty-rosters", DutyRosterViewSet, basename="duty-roster")
router.register(r"hr/roster-slots", RosterSlotViewSet, basename="roster-slot")

urlpatterns = router.urls
