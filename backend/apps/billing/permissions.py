"""
Billing permissions — faturista or admin required for all billing views.
"""

from rest_framework.permissions import BasePermission


class IsFaturistaOrAdmin(BasePermission):
    """Allow access only to users with the 'faturista' or 'admin' role."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.has_role_permission("billing.read") or user.has_role_permission("billing.write")
