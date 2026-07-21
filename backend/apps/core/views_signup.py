"""
S-132: Public self-serve clinic signup.

A clinic fills in name + CNPJ + email on the marketing site and gets a fully
provisioned, functional trial tenant in minutes — no engineer, no
``provision_tenant.sh``. The owner activates by clicking the welcome email's
set-password link (which flips the tenant PENDING → TRIAL).

Billing (Asaas recurring subscription) is wired best-effort: a gateway outage
must never block provisioning, so failures are logged and the tenant is left in
TRIAL with empty Asaas IDs for ops to retry. The subscription webhook flips
TRIAL → ACTIVE on first confirmed payment.
"""

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .models import Tenant, User
from .serializers import SelfServeSignupSerializer
from .services.provisioning import ProvisioningError, generate_unique_slug, provision_tenant

logger = logging.getLogger(__name__)


class SignupRateThrottle(AnonRateThrottle):
    """Signups create a PG schema each — keep abuse cheap to absorb."""

    rate = "5/hour"
    scope = "signup"


def _attach_asaas_billing(subscription, *, tenant, cnpj, email) -> None:
    """Best-effort: create the Asaas customer + recurring subscription.

    Never raises — billing setup is decoupled from provisioning so the clinic is
    usable immediately even if the gateway is down.
    """
    if subscription is None:
        return
    try:
        from apps.billing.services.asaas import AsaasService

        service = AsaasService()
        customer_id = service.create_clinic_customer(
            name=tenant.name, email=email, cnpj=cnpj, external_ref=str(tenant.id)
        )
        remote = service.create_subscription(
            customer_id=customer_id,
            value=subscription.monthly_price,
            next_due_date=subscription.current_period_end.isoformat(),
            description=f"Assinatura Vitali — {tenant.name}",
            external_ref=str(tenant.id),
        )
        subscription.asaas_customer_id = customer_id
        subscription.asaas_subscription_id = remote.get("id", "")
        subscription.save(update_fields=["asaas_customer_id", "asaas_subscription_id"])
        logger.info("signup.billing.ok tenant=%s sub=%s", tenant.slug, remote.get("id"))
    except Exception as exc:  # noqa: BLE001 — billing is best-effort
        logger.warning("signup.billing.deferred tenant=%s err=%s", tenant.slug, exc)


class SelfServeSignupView(APIView):
    """POST /api/v1/public/signup/ — provision a trial tenant for a new clinic."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [SignupRateThrottle]

    def post(self, request):
        serializer = SelfServeSignupSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Dados inválidos.",
                        "details": serializer.errors,
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        email = data["email"]

        # Reject duplicate owner email up front (User.email is globally unique)
        # so we never build a schema we'd just have to roll back.
        if User.objects.filter(email=email).exists():
            return Response(
                {
                    "error": {
                        "code": "EMAIL_TAKEN",
                        "message": "Já existe uma conta com este e-mail.",
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )

        owner_full_name = data.get("owner_full_name") or data["company_name"]
        slug = generate_unique_slug(data["company_name"])

        try:
            result = provision_tenant(
                name=data["company_name"],
                slug=slug,
                cnpj=data["cnpj"],
                owner_email=email,
                owner_full_name=owner_full_name,
                owner_password=None,  # passwordless — activates via welcome link
                host=request.get_host(),
                status=Tenant.Status.PENDING,
                send_welcome=True,
            )
        except ProvisioningError as exc:
            if str(exc) == "OWNER_EMAIL_TAKEN":
                return Response(
                    {
                        "error": {
                            "code": "EMAIL_TAKEN",
                            "message": "Já existe uma conta com este e-mail.",
                        }
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            logger.error("signup.failed slug=%s err=%s", slug, exc)
            return Response(
                {
                    "error": {
                        "code": "SIGNUP_FAILED",
                        "message": "Falha ao criar a clínica. Nenhum dado parcial foi mantido; tente novamente.",
                    }
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        _attach_asaas_billing(
            result.subscription, tenant=result.tenant, cnpj=data["cnpj"], email=email
        )

        return Response(
            {
                "tenant": {
                    "id": str(result.tenant.id),
                    "name": result.tenant.name,
                    "slug": result.tenant.slug,
                    "status": result.tenant.status,
                    "trial_ends_at": result.tenant.trial_ends_at,
                },
                "domain": result.domain.domain,
                "owner_email": email,
                "message": (
                    "Clínica criada! Enviamos um e-mail para você definir sua senha "
                    "e acessar o sistema."
                ),
            },
            status=status.HTTP_201_CREATED,
        )
