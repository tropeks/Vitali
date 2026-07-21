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
from .services.provisioning import (
    ProvisioningConflict,
    ProvisioningError,
    generate_unique_slug,
    provision_tenant,
)

logger = logging.getLogger(__name__)

# Friendly 409 messages keyed by ProvisioningConflict.code.
_CONFLICT_MESSAGES = {
    "CNPJ_TAKEN": "Já existe uma clínica cadastrada com este CNPJ.",
    "EMAIL_TAKEN": "Já existe uma conta com este e-mail.",
    "SLUG_TAKEN": "Não foi possível reservar o endereço da clínica. Tente novamente.",
    "CONFLICT": "Estes dados já estão em uso. Tente novamente.",
}


class SignupRateThrottle(AnonRateThrottle):
    """Signups create a PG schema each — keep abuse cheap to absorb.

    This 5/hour bucket is the *only* defense on an anonymous endpoint that
    provisions a PG schema + runs migrations (expensive). The bucket key is the
    client IP from ``BaseThrottle.get_ident``, which trusts ``REST_FRAMEWORK
    ["NUM_PROXIES"]`` (=1, we sit behind a single nginx hop) to read the real
    client IP off X-Forwarded-For instead of the whole spoofable XFF string —
    without it, an attacker rotates XFF to mint unlimited buckets and bypasses
    the throttle entirely. See vitali/settings/base.py NUM_PROXIES.
    """

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
        cnpj = data["cnpj"]

        # Reject known duplicates up front — email AND CNPJ are both unique — so
        # the expensive schema build never even starts for the common re-signup
        # case (these run BEFORE provision_tenant; a genuine concurrent race that
        # slips past the check is still caught as a 409 via ProvisioningConflict).
        if User.objects.filter(email=email).exists():
            return Response(
                {
                    "error": {
                        "code": "EMAIL_TAKEN",
                        "message": _CONFLICT_MESSAGES["EMAIL_TAKEN"],
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )
        if cnpj and Tenant.objects.filter(cnpj=cnpj).exists():
            return Response(
                {
                    "error": {
                        "code": "CNPJ_TAKEN",
                        "message": _CONFLICT_MESSAGES["CNPJ_TAKEN"],
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
                cnpj=cnpj,
                owner_email=email,
                owner_full_name=owner_full_name,
                owner_password=None,  # passwordless — activates via welcome link
                host=request.get_host(),
                status=Tenant.Status.PENDING,
                send_welcome=True,
            )
        except ProvisioningConflict as exc:
            # Duplicate CNPJ/email or a slug race (incl. concurrent signups that
            # beat the up-front checks) → friendly 409, never a 500.
            logger.info("signup.conflict slug=%s code=%s", slug, exc.code)
            return Response(
                {
                    "error": {
                        "code": exc.code,
                        "message": _CONFLICT_MESSAGES.get(exc.code, _CONFLICT_MESSAGES["CONFLICT"]),
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )
        except ProvisioningError as exc:
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
