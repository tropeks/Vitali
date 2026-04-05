"""
Core views — Auth, Tenant registration, User management.
"""
import logging
from datetime import timedelta

from django.contrib.auth import update_session_auth_hash
from django.core.cache import cache
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import generics, permissions, status
from rest_framework import throttling as rest_framework_throttling
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView as _BaseRefreshView

from .models import AuditLog, Domain, FeatureFlag, Role, Tenant, TUSSSyncLog, User
from .serializers import (
    ChangePasswordSerializer,
    FeatureFlagSerializer,
    HealthOSTokenObtainPairSerializer,
    LoginSerializer,
    RoleSerializer,
    TenantRegistrationSerializer,
    UserCreateSerializer,
    UserDTOSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)

# ─── Lockout configuration ────────────────────────────────────────────────────
# Thresholds: (attempt_count, lockout_seconds)
LOCKOUT_THRESHOLDS = [
    (5, 5 * 60),    # 5 failures → lock 5 min
    (10, 30 * 60),  # 10 failures → lock 30 min
    (15, 60 * 60),  # 15 failures → lock 1 h
]
MAX_TRACKED_ATTEMPTS = 20


def _lockout_key(ip: str, email: str) -> str:
    return f"login_attempts:{ip}:{email.lower()}"


def _get_client_ip(request) -> str:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _get_lockout_ttl(attempts: int) -> int | None:
    """Return the lockout TTL in seconds for the given attempt count, or None."""
    ttl = None
    for threshold, seconds in LOCKOUT_THRESHOLDS:
        if attempts >= threshold:
            ttl = seconds
    return ttl


def _increment_attempts(ip: str, email: str) -> int:
    key = _lockout_key(ip, email)
    try:
        attempts = cache.get(key, 0) + 1
        ttl = _get_lockout_ttl(attempts) or (60 * 60)  # default 1h TTL
        cache.set(key, attempts, timeout=ttl)
        return attempts
    except Exception:
        return 0


def _clear_attempts(ip: str, email: str):
    try:
        cache.delete(_lockout_key(ip, email))
    except Exception:
        pass


def _is_locked_out(ip: str, email: str) -> tuple[bool, int]:
    """Returns (is_locked, seconds_remaining)."""
    key = _lockout_key(ip, email)
    try:
        attempts = cache.get(key, 0)
        ttl = _get_lockout_ttl(attempts)
        if ttl:
            remaining = cache.ttl(key) if hasattr(cache, "ttl") else ttl
            return True, remaining or ttl
    except Exception:
        pass
    return False, 0


def _write_audit(request, user, action: str, resource_type: str = "auth", resource_id: str = ""):
    try:
        AuditLog.objects.create(
            user=user if (user and getattr(user, "pk", None)) else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id or "",
            ip_address=_get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )
    except Exception as exc:
        logger.warning("Failed to write audit log: %s", exc)


# ─── Auth Views ───────────────────────────────────────────────────────────────

class LoginRateThrottle(rest_framework_throttling.AnonRateThrottle):
    """5 login attempts per minute per IP — tighter than the global 100/hour."""
    rate = "5/min"
    scope = "login"


class LoginView(APIView):
    """
    POST /api/v1/auth/login
    Rate limit via Redis, account lockout, Argon2id password check.
    Returns { access, refresh, user: UserDTO }
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "message": "Dados inválidos.", "details": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]
        ip = _get_client_ip(request)

        # Check lockout
        locked, remaining = _is_locked_out(ip, email)
        if locked:
            return Response(
                {
                    "error": {
                        "code": "ACCOUNT_LOCKED",
                        "message": "Conta temporariamente bloqueada por excesso de tentativas.",
                        "retry_after": remaining,
                    }
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Authenticate
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            attempts = _increment_attempts(ip, email)
            _write_audit(request, None, "login_failed", resource_id=email)
            return Response(
                {"error": {"code": "INVALID_CREDENTIALS", "message": "Credenciais inválidas."}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.check_password(password):
            attempts = _increment_attempts(ip, email)
            _write_audit(request, user, "login_failed", resource_id=str(user.pk))
            locked, remaining = _is_locked_out(ip, email)
            resp = {"error": {"code": "INVALID_CREDENTIALS", "message": "Credenciais inválidas."}}
            if locked:
                resp["error"]["code"] = "ACCOUNT_LOCKED"
                resp["error"]["retry_after"] = remaining
            return Response(resp, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_active:
            return Response(
                {"error": {"code": "USER_INACTIVE", "message": "Conta desativada."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Success — clear attempts, issue tokens
        _clear_attempts(ip, email)
        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        refresh = RefreshToken.for_user(user)
        refresh["email"] = user.email
        refresh["full_name"] = user.full_name
        refresh["role"] = user.role.name if user.role else None

        _write_audit(request, user, "login_success", resource_id=str(user.pk))

        user_dto = UserDTOSerializer(user, context={"request": request}).data
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": user_dto,
        })


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout
    Blacklists the refresh token.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"error": {"code": "MISSING_TOKEN", "message": "refresh token obrigatório."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as exc:
            return Response(
                {"error": {"code": "INVALID_TOKEN", "message": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _write_audit(request, request.user, "logout", resource_id=str(request.user.pk))
        return Response({"detail": "Logout realizado com sucesso."})


class TokenRefreshView(_BaseRefreshView):
    """POST /api/v1/auth/refresh — wraps SimpleJWT with rotation."""
    pass


class ChangePasswordView(APIView):
    """PUT /api/v1/auth/password"""
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "message": "Dados inválidos.", "details": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user
        if not user.check_password(serializer.validated_data["current_password"]):
            return Response(
                {"error": {"code": "WRONG_PASSWORD", "message": "Senha atual incorreta."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])

        _write_audit(request, user, "password_changed", resource_id=str(user.pk))
        return Response({"detail": "Senha alterada com sucesso."})


class MeView(APIView):
    """GET /api/v1/me — return current user DTO."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserDTOSerializer(request.user, context={"request": request})
        return Response(serializer.data)


# ─── Tenant Registration (public schema) ──────────────────────────────────────

class TenantRegistrationView(APIView):
    """
    POST /api/v1/platform/tenants
    Creates a new tenant + schema + domain + admin role + admin user.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = TenantRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "message": "Dados inválidos.", "details": serializer.errors}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        # 1. Create Tenant (auto_create_schema=True → creates the PG schema)
        tenant = Tenant(
            name=data["name"],
            slug=data["slug"],
            cnpj=data.get("cnpj", ""),
            status=Tenant.Status.TRIAL,
            trial_ends_at=timezone.now() + timedelta(days=14),
        )
        tenant.save()  # triggers schema creation

        # 2. Create domain
        host = request.get_host().split(":")[0]
        # Use slug.localhost for dev, slug.vitali.com.br in production
        if "localhost" in host or "127.0.0.1" in host:
            domain_url = f"{tenant.slug}.localhost"
        else:
            base = host.split(".", 1)[-1] if "." in host else host
            domain_url = f"{tenant.slug}.{base}"

        domain = Domain.objects.create(
            domain=domain_url,
            tenant=tenant,
            is_primary=True,
        )

        # 3. Inside the new schema: create admin Role + admin User
        admin_user_data = {}
        with schema_context(tenant.schema_name):
            from .permissions import DEFAULT_ROLES

            # Create all default roles
            roles_created = {}
            for role_name, perms in DEFAULT_ROLES.items():
                role = Role.objects.create(
                    name=role_name,
                    permissions=perms,
                    is_system=True,
                )
                roles_created[role_name] = role

            admin_role = roles_created["admin"]

            # Create admin user
            admin_user = User(
                email=data["admin_email"],
                full_name=data["admin_full_name"],
                role=admin_role,
                is_active=True,
                is_staff=True,
            )
            admin_user.set_password(data["admin_password"])
            admin_user.save()

            admin_user_data = {
                "id": str(admin_user.pk),
                "email": admin_user.email,
                "full_name": admin_user.full_name,
                "role": admin_role.name,
            }

        return Response(
            {
                "tenant": {
                    "id": str(tenant.pk),
                    "name": tenant.name,
                    "slug": tenant.slug,
                    "schema_name": tenant.schema_name,
                    "status": tenant.status,
                    "trial_ends_at": tenant.trial_ends_at,
                },
                "domain": domain.domain,
                "admin_user": admin_user_data,
                "trial_ends_at": tenant.trial_ends_at,
            },
            status=status.HTTP_201_CREATED,
        )


# ─── Legacy JWT view ──────────────────────────────────────────────────────────

class HealthOSTokenObtainPairView(TokenObtainPairView):
    serializer_class = HealthOSTokenObtainPairSerializer


# ─── User & Role views ────────────────────────────────────────────────────────

class UserListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):
        return User.objects.select_related("role").filter(is_active=True)


class UserDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer
    queryset = User.objects.all()
    lookup_field = "id"


class RoleListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RoleSerializer
    queryset = Role.objects.all()


# ─── Feature flags view ───────────────────────────────────────────────────────

class TenantFeaturesView(APIView):
    """
    GET /api/v1/core/features/
    Returns the list of active modules for the current tenant.
    Used by the frontend useHasModule() hook to hide/show nav items.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not hasattr(request, "tenant"):
            return Response({"active_modules": []})
        flags = FeatureFlag.objects.filter(tenant=request.tenant, is_enabled=True)
        return Response({"active_modules": [f.module_key for f in flags]})


# ─── AI: TUSS Sync Status ─────────────────────────────────────────────────────

class TUSSSyncStatusView(APIView):
    """
    GET /api/v1/ai/tuss-sync-status/
    Admin-only. Returns the last 5 TUSS sync log entries and table row count.
    Used by billing overview to show the TUSS DB sync badge.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Admin-only: require is_staff or admin role
        if not (request.user.is_staff or request.user.is_superuser or
                request.user.has_role_permission("users.read")):
            from rest_framework.response import Response as Resp
            from rest_framework import status as drf_status
            return Resp({"detail": "Forbidden."}, status=drf_status.HTTP_403_FORBIDDEN)

        last_syncs = list(
            TUSSSyncLog.objects.order_by("-ran_at")[:5].values(
                "id", "ran_at", "status", "source",
                "row_count_total", "row_count_added", "row_count_updated",
                "duration_ms", "error_message",
            )
        )

        # Compute age of last sync in days
        last_sync_age_days = None
        if last_syncs:
            from django.utils import timezone as tz
            age = tz.now() - last_syncs[0]["ran_at"]
            last_sync_age_days = age.days

        table_row_count = TUSSSyncLog.objects.using("default").values("id").count()
        # row count is from TUSSCode (the table being synced)
        from apps.core.models import TUSSCode as _TUSSCode
        table_row_count = _TUSSCode.objects.using("default").filter(active=True).count()

        return Response({
            "last_syncs": last_syncs,
            "table_row_count": table_row_count,
            "last_sync_age_days": last_sync_age_days,
        })
