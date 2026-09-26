"""
Management command: provision_tenant (ordem 022)

Usage:
    python manage.py provision_tenant \
        --slug clinica-boa-saude --name "Clínica Boa Saúde" \
        --domain clinica-boa-saude.vitali.app \
        --owner-email dono@clinica.com --owner-name "Dono da Clínica" \
        --cnpj 11.222.333/0001-81 --modules emr,billing

Replaces the four legacy ways of creating a tenant (see the order) with ONE:
this is a thin wrapper over ``apps.core.services.provisioning.provision_tenant``
— the SAME function ``views_signup.SelfServeSignupView`` (public self-serve
signup) and ``apps.core.views.TenantRegistrationView`` (platform-operator API)
call. No logic of its own creates a Tenant/Domain/Role/User/Subscription; it
only parses arguments and calls the service.

Every value here is DATA an argparse string turns into a Python kwarg — never
source fed to a shell or interpolated into a Python/SQL blob. This is the exact
defect ``scripts/provision_tenant.sh`` had (a clinic name with an apostrophe
broke the ``manage.py shell -c`` string it was spliced into; a name crafted for
it ran arbitrary code with the whole database's credentials). This command has
no shell in its call chain at all.

No ``--password``/``--owner-password``/anything like it exists, on purpose:
the parser simply never defines such an argument, so passing one is a plain
"unrecognized arguments" argparse error, not a feature to disable. The owner is
born without a usable password (``set_unusable_password``) and activates
through the same set-password welcome link self-serve signup issues
(``services.invitations.issue_password_set_invitation``) — the token is never
written to stdout/stderr/logs, only "convite de ativação emitido para <email>".

Idempotent: re-running with the exact same arguments against an
already-provisioned slug reports "já existe" for each piece and creates
NOTHING (no new schema, no new anything). Any argument that disagrees with
what is already on record for that slug (name, domain, owner e-mail, cnpj,
modules) is a named ``CommandError`` — the existing tenant is never touched. A
domain or owner e-mail that already belongs to a DIFFERENT tenant is also a
named ``CommandError`` (via ``provisioning.ProvisioningConflict``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core import partitioning
from apps.core.constants import ALLOWED_MODULE_KEYS
from apps.core.models import (
    Domain,
    FeatureFlag,
    Subscription,
    Tenant,
    User,
    UserTenantMembership,
)
from apps.core.services.provisioning import (
    ProvisioningConflict,
    ProvisioningError,
    provision_tenant,
)

_CONFLICT_DETAILS = {
    "EMAIL_TAKEN": "e-mail do dono já pertence a outro usuário/tenant",
    "DOMAIN_TAKEN": "domínio já pertence a outro tenant",
    "CNPJ_TAKEN": "cnpj já cadastrado em outro tenant",
    "SLUG_TAKEN": "slug já está em uso (corrida concorrente)",
}


def _parse_modules(raw: str | None) -> list[str] | None:
    """``None`` means "caller didn't pass --modules, use the settings default".
    An explicit value is validated against ``ALLOWED_MODULE_KEYS`` — an
    unknown module key names itself in the error, never a silent no-op."""
    if not raw:
        return None
    modules = [m.strip() for m in raw.split(",") if m.strip()]
    unknown = sorted(set(modules) - ALLOWED_MODULE_KEYS)
    if unknown:
        raise CommandError(
            f"módulo(s) desconhecido(s): {', '.join(unknown)}. "
            f"Permitidos: {', '.join(sorted(ALLOWED_MODULE_KEYS))}"
        )
    return modules


def _wanted_modules(modules: list[str] | None) -> list[str]:
    if modules is not None:
        return sorted(modules)
    return sorted(getattr(settings, "SELF_SERVE_DEFAULT_MODULES", ["emr"]))


def _admin_membership(tenant):
    return (
        UserTenantMembership.objects.filter(tenant=tenant, role__name="admin", is_active=True)
        .select_related("user", "role")
        .order_by("created_at")
        .first()
    )


def _active_modules(tenant) -> list[str]:
    subscription = Subscription.objects.filter(tenant=tenant).order_by("-created_at").first()
    return sorted(subscription.active_modules) if subscription else []


def _audit_leaves_exist(tenant) -> bool:
    today = timezone.now().date()
    return all(
        partitioning.partition_exists(
            partitioning.tenant_partition_name(
                partitioning.month_partition_name(month), tenant.schema_name
            )
        )
        for month in partitioning.month_starts(2, today=today)
    )


@dataclass(frozen=True)
class _Requested:
    """What the caller asked for — grouped so it travels as ONE argument
    through the idempotency-check functions below, instead of five loose ones."""

    name: str
    domain: str
    owner_email: str
    cnpj: str
    modules: list[str] | None


@dataclass(frozen=True)
class _ExistingState:
    """What is ALREADY on record for a previously-provisioned slug — read
    once, then both diffed against ``_Requested`` and printed, so the two
    never drift apart by reading the DB twice with different queries."""

    domain: Domain | None
    membership: UserTenantMembership | None
    modules: list[str] = field(default_factory=list)
    flag_keys: list[str] = field(default_factory=list)
    audit_leaves_ok: bool = False

    @classmethod
    def load(cls, tenant) -> _ExistingState:
        return cls(
            domain=Domain.objects.filter(tenant=tenant, is_primary=True).first(),
            membership=_admin_membership(tenant),
            modules=_active_modules(tenant),
            flag_keys=sorted(
                FeatureFlag.objects.filter(tenant=tenant, is_enabled=True).values_list(
                    "module_key", flat=True
                )
            ),
            audit_leaves_ok=_audit_leaves_exist(tenant),
        )

    def diff(self, tenant, requested: _Requested) -> list[str]:
        conflicts: list[str] = []
        if tenant.name != requested.name:
            conflicts.append(f"name: pedido={requested.name!r} existente={tenant.name!r}")
        if requested.cnpj and (tenant.cnpj or "") != requested.cnpj:
            conflicts.append(f"cnpj: pedido={requested.cnpj!r} existente={tenant.cnpj!r}")

        own_domain = self.domain.domain if self.domain else None
        if own_domain != requested.domain:
            conflicts.append(f"domain: pedido={requested.domain!r} existente={own_domain!r}")
        foreign_domain = (
            Domain.objects.filter(domain=requested.domain).exclude(tenant=tenant).first()
        )
        if foreign_domain is not None:
            conflicts.append(
                f"domain: {requested.domain!r} já pertence ao tenant {foreign_domain.tenant.slug!r}"
            )

        conflicts.extend(self._owner_conflicts(requested.owner_email))

        wanted_modules = _wanted_modules(requested.modules)
        if self.modules != wanted_modules:
            conflicts.append(f"modules: pedido={wanted_modules} existente={self.modules}")

        return conflicts

    def _owner_conflicts(self, owner_email: str) -> list[str]:
        conflicts = []
        if self.membership is None:
            conflicts.append("owner_email: nenhuma membership admin encontrada para este tenant")
        elif self.membership.user.email.lower() != owner_email:
            conflicts.append(
                f"owner_email: pedido={owner_email!r} existente={self.membership.user.email!r}"
            )

        owner_qs = User.objects.filter(email=owner_email)
        if self.membership is not None:
            owner_qs = owner_qs.exclude(pk=self.membership.user_id)
        if owner_qs.exists():
            conflicts.append(f"owner_email: {owner_email!r} já pertence a outro usuário")
        return conflicts

    def report_lines(self, tenant) -> list[str]:
        owner_email = self.membership.user.email if self.membership else "(nenhum)"
        return [
            f"já existe: tenant {tenant.slug}",
            f"já existe: domínio {self.domain.domain if self.domain else '(nenhum)'}",
            "já existe: papéis de sistema (globais, compartilhados entre clínicas)",
            f"já existe: dono {owner_email}",
            "já existe: membership do dono" if self.membership else "AVISO: sem membership admin",
            f"já existe: assinatura (módulos: {', '.join(self.modules) or '(nenhum)'})",
            f"já existe: flags ({', '.join(self.flag_keys) or '(nenhuma)'})",
            (
                "já existe: folhas de auditoria (mês atual e seguinte)"
                if self.audit_leaves_ok
                else "AVISO: folha de auditoria ausente para o mês atual/seguinte"
            ),
        ]


class Command(BaseCommand):
    help = (
        "Provisiona uma clínica (tenant + domínio + papéis + dono + assinatura trial + "
        "partições de auditoria) chamando o MESMO serviço que o signup usa. Casca fina: "
        "nenhuma lógica de criação própria, e sem argumento de senha."
    )

    def add_arguments(self, parser):
        parser.allow_abbrev = False  # "--pass" nunca deve casar por abreviação
        parser.add_argument("--slug", required=True, help="Slug/schema_name da clínica.")
        parser.add_argument("--name", required=True, help="Nome de exibição da clínica.")
        parser.add_argument(
            "--domain",
            required=True,
            help="Hostname de roteamento, explícito (ex.: clinica.vitali.app).",
        )
        parser.add_argument("--owner-email", required=True, dest="owner_email")
        parser.add_argument("--owner-name", required=True, dest="owner_name")
        parser.add_argument("--cnpj", default="", help="Opcional.")
        parser.add_argument(
            "--modules",
            default=None,
            help=(
                "Chaves de módulo separadas por vírgula (ex.: emr,billing). Permitidas: "
                f"{', '.join(sorted(ALLOWED_MODULE_KEYS))}. Default: "
                "settings.SELF_SERVE_DEFAULT_MODULES."
            ),
        )

    def handle(self, *args, **options):
        slug = options["slug"].strip()
        owner_name = options["owner_name"]
        requested = _Requested(
            name=options["name"],
            domain=options["domain"].strip(),
            owner_email=options["owner_email"].strip().lower(),
            cnpj=(options["cnpj"] or "").strip(),
            modules=_parse_modules(options["modules"]),
        )

        existing = Tenant.objects.filter(slug=slug).first()
        if existing is not None:
            self._reconcile_existing(existing, requested)
            return

        self._provision_new(slug, requested, owner_name=owner_name)

    def _provision_new(self, slug: str, requested: _Requested, *, owner_name: str) -> None:
        try:
            result = provision_tenant(
                name=requested.name,
                slug=slug,
                cnpj=requested.cnpj,
                owner_email=requested.owner_email,
                owner_full_name=owner_name,
                owner_password=None,  # sem senha na linha de comando — ver docstring
                domain=requested.domain,
                modules=requested.modules,
                # PENDING, como o signup: o dono nasce sem senha e a ativação
                # pelo convite (SetPasswordView) é que leva a clínica a TRIAL.
                status=Tenant.Status.PENDING,
                create_subscription=True,
                send_welcome=True,
            )
        except ProvisioningConflict as exc:
            detail = _CONFLICT_DETAILS.get(exc.code, f"conflito ({exc.code})")
            raise CommandError(f"não foi possível provisionar {slug!r}: {detail}") from exc
        except ProvisioningError as exc:
            raise CommandError(f"falha ao provisionar {slug!r}: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"clínica {result.tenant.slug!r} provisionada"))
        self.stdout.write(f"domínio: {result.domain.domain}")
        self.stdout.write(f"convite de ativação emitido para {result.owner.email}")

    def _reconcile_existing(self, tenant, requested: _Requested) -> None:
        state = _ExistingState.load(tenant)
        conflicts = state.diff(tenant, requested)
        if conflicts:
            raise CommandError(
                f"tenant {tenant.slug!r} já existe com dados divergentes: " + "; ".join(conflicts)
            )
        for line in state.report_lines(tenant):
            self.stdout.write(self.style.SUCCESS(line))
        self.stdout.write(
            self.style.SUCCESS(f"nada criado — {tenant.slug!r} já estava provisionado")
        )
