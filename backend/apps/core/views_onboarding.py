"""
S-043: Onboarding checklist view.
GET /api/v1/core/onboarding/ — returns completion status of 5 key first steps.
Server-side checks against real DB state; never drifts from reality.
"""
from apps.billing.models import TISSGuide
from apps.emr.models import Appointment, Encounter, Patient
from apps.pharmacy.models import StockItem
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class OnboardingView(APIView):
    """
    GET /api/v1/core/onboarding/
    Returns ordered list of onboarding steps with done=true/false.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not hasattr(request, "tenant"):
            return Response({"steps": [], "completed": 0, "total": 0, "all_done": True})

        steps = [
            {
                "id": "first_patient",
                "label": "Cadastrar primeiro paciente",
                "done": Patient.objects.exists(),
                "action_url": "/patients/new",
            },
            {
                "id": "first_appointment",
                "label": "Agendar primeira consulta",
                "done": Appointment.objects.exists(),
                "action_url": "/scheduling/new",
            },
            {
                "id": "first_encounter",
                "label": "Registrar primeiro atendimento",
                "done": Encounter.objects.exists(),
                "action_url": "/emr/encounters/new",
            },
            {
                "id": "first_guide",
                "label": "Criar primeira guia TISS",
                "done": TISSGuide.objects.exists(),
                "action_url": "/billing/guides/new",
            },
            {
                "id": "first_stock_item",
                "label": "Cadastrar item no estoque",
                "done": StockItem.objects.exists(),
                "action_url": "/farmacia/estoque/new",
            },
        ]

        all_done = all(s["done"] for s in steps)
        completed_count = sum(1 for s in steps if s["done"])

        return Response({
            "steps": steps,
            "completed": completed_count,
            "total": len(steps),
            "all_done": all_done,
        })
