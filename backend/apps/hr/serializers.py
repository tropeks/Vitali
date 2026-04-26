"""DRF serializers for HR models."""

from rest_framework import serializers

from .models import Employee


class EmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    role = serializers.CharField(source="user.role.name", read_only=True, default=None)

    class Meta:
        model = Employee
        fields = [
            "id",
            "user",
            "full_name",
            "email",
            "role",
            "hire_date",
            "employment_status",
            "contract_type",
            "terminated_at",
            "created_at",
        ]
        read_only_fields = ["id", "user", "created_at"]
