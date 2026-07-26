"""Django admin registration for HR models."""

from django.contrib import admin

from .models import (
    Dependent,
    DutyRoster,
    Employee,
    EmployeeAssignment,
    LeaveRequest,
    OccupationalHealthExam,
    Position,
    RosterSlot,
    TimeEntry,
    WorkSchedule,
)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ["user", "employment_status", "contract_type", "hire_date"]
    list_filter = ["employment_status", "contract_type"]
    search_fields = ["user__full_name", "user__email"]
    readonly_fields = ["id", "created_at", "updated_at"]


admin.site.register(WorkSchedule)
admin.site.register(TimeEntry)
admin.site.register(OccupationalHealthExam)
admin.site.register(Position)
admin.site.register(EmployeeAssignment)
admin.site.register(Dependent)
admin.site.register(LeaveRequest)
admin.site.register(DutyRoster)
admin.site.register(RosterSlot)
