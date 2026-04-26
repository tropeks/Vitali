"""Django admin registration for HR models."""

from django.contrib import admin

from .models import Employee


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ["user", "employment_status", "contract_type", "hire_date"]
    list_filter = ["employment_status", "contract_type"]
    search_fields = ["user__full_name", "user__email"]
    readonly_fields = ["id", "created_at", "updated_at"]
