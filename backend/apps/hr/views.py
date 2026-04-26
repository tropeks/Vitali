"""HR ViewSets — list/retrieve/update only.

Create/destroy are intentionally excluded — those go through the service-layer
orchestrator (EmployeeOnboardingService / EmployeeOffboardingService) added in
T3/T4. This keeps the cascade pattern explicit and avoids relying on signals.
"""

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from .models import Employee
from .serializers import EmployeeSerializer


class EmployeeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Employee.objects.select_related("user__role").all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Employee.objects.select_related("user__role").all()
        include_terminated = (
            self.request.query_params.get("include_terminated", "").lower() == "true"
        )
        if not include_terminated:
            qs = qs.filter(employment_status="active")
        return qs
