"""
Ordem 022 — ``manage.py provision_tenant``: casca fina sobre o serviço único.

Cada teste que provisiona uma clínica de verdade constrói um schema PG real
(``Tenant.auto_create_schema`` é True por padrão) — leva de ~1 a ~3 minutos.
Por isso os testes aqui agrupam várias asserções por schema real construído,
em vez de um schema por asserção (ver a ordem, "Minimize schemas reais").

Cobertura, por classe:

* ``ProvisionTenantCommandParityTests`` — o comando entrega a MESMA clínica
  que o signup entrega (campo a campo), isolamento entre duas clínicas, valor
  hostil gravado literal (não interpretado — não há shell/eval no caminho) e
  retenção de auditoria no padrão de fábrica (240 meses, expurgo desligado).
* ``ProvisionTenantCommandIdempotencyTests`` — reexecutar com os MESMOS
  argumentos não cria nada e relata "já existe" item a item; qualquer
  argumento divergente é um ``CommandError`` nomeando o campo; o token do
  convite de ativação nunca aparece em stdout nem em log.
* ``ProvisionTenantCommandRollbackTests`` — domínio/e-mail de OUTRO tenant é
  conflito nomeado; o mesmo slug com dados divergentes não toca o tenant
  existente (nem no atalho do comando, nem no ``IntegrityError`` do próprio
  serviço); uma falha forçada APÓS o schema derruba só a clínica nova.
* ``ProvisionTenantCommandParserTests`` — o parser recusa qualquer variação
  de argumento de senha, e um módulo desconhecido em ``--modules`` é
  rejeitado antes de qualquer provisionamento (nenhum schema real).
"""

from __future__ import annotations

import datetime
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from apps.core import partitioning
from apps.core.management.commands.purge_audit_logs import _resolve_retention
from apps.core.models import (
    Domain,
    FeatureFlag,
    Subscription,
    Tenant,
    TenantAuditRetention,
    UserTenantMembership,
)
from apps.core.services import provisioning


def _next_month(for_date: datetime.date) -> datetime.date:
    return (
        datetime.date(for_date.year + 1, 1, 1)
        if for_date.month == 12
        else datetime.date(for_date.year, for_date.month + 1, 1)
    )


def _audit_leaves_ok(tenant: Tenant) -> bool:
    today = timezone.now().date()
    return all(
        partitioning.partition_exists(
            partitioning.tenant_partition_name(
                partitioning.month_partition_name(d), tenant.schema_name
            )
        )
        for d in (today, _next_month(today))
    )


def _tenant_state(tenant: Tenant) -> SimpleNamespace:
    """The structurally-comparable shape of a freshly-provisioned clinic —
    everything that should be identical regardless of WHICH caller
    (command, signup, platform API) built it."""
    domain = Domain.objects.get(tenant=tenant, is_primary=True)
    membership = UserTenantMembership.objects.get(tenant=tenant)
    owner = membership.user
    subscription = Subscription.objects.get(tenant=tenant)
    flag_keys = tuple(
        sorted(
            FeatureFlag.objects.filter(tenant=tenant, is_enabled=True).values_list(
                "module_key", flat=True
            )
        )
    )
    return SimpleNamespace(
        domain_is_primary=domain.is_primary,
        owner_is_staff=owner.is_staff,
        owner_has_usable_password=owner.has_usable_password(),
        owner_must_change_password=owner.must_change_password,
        owner_role_name=owner.role.name if owner.role else None,
        membership_is_active=membership.is_active,
        membership_role_name=membership.role.name if membership.role else None,
        subscription_status=subscription.status,
        subscription_modules=tuple(sorted(subscription.active_modules)),
        subscription_plan_name=subscription.plan.name,
        flag_keys=flag_keys,
        audit_leaves_ok=_audit_leaves_ok(tenant),
    )


def _isolation_snapshot(tenant: Tenant) -> tuple:
    """A narrower snapshot for proving provisioning tenant B never touched
    tenant A: specific row identities (ids), not just "looks right"."""
    tenant.refresh_from_db()
    membership = UserTenantMembership.objects.get(tenant=tenant)
    subscription = Subscription.objects.get(tenant=tenant)
    flags = tuple(
        sorted(FeatureFlag.objects.filter(tenant=tenant).values_list("module_key", flat=True))
    )
    return (tenant.name, tenant.status, membership.id, subscription.id, flags)


class ProvisionTenantCommandParityTests(TestCase):
    """O comando entrega a mesma clínica que o signup, campo a campo — e não
    interfere numa segunda clínica provisionada em seguida."""

    HOSTILE_NAME = "Clínica D'Ávila \"x\"; __import__('os').system('id')\nlinha2"

    def test_command_and_signup_produce_the_same_shape_of_clinic(self):
        # --- A: manage.py provision_tenant. --name carrega o valor hostil:
        # entra como argparse string -> kwarg Python, nunca como shell/SQL.
        call_command(
            "provision_tenant",
            "--slug",
            "parity-a-022",
            "--name",
            self.HOSTILE_NAME,
            "--domain",
            "parity-a-022.vitali.app",
            "--owner-email",
            "owner.paritya022@clinica.com",
            "--owner-name",
            "Dono A",
            "--cnpj",
            "11111111000101",
            "--modules",
            "emr,billing",
            stdout=StringIO(),
        )
        tenant_a = Tenant.objects.get(slug="parity-a-022")

        # Gravado literal — se qualquer coisa no caminho tentasse interpretar
        # isto como shell/Python/SQL, o comando teria explodido ou o valor
        # armazenado seria outra coisa.
        self.assertEqual(tenant_a.name, self.HOSTILE_NAME)

        snapshot_a = _isolation_snapshot(tenant_a)

        # A's owner User INSERT carries a DEFERRABLE INITIALLY DEFERRED FK
        # check (same one apps.core.partitioning.drop_partition documents)
        # that stays pending until commit — but this test's transaction never
        # commits between A and B. Building B's real schema runs an ALTER
        # TABLE core_user migration, and Postgres refuses to ALTER a table
        # with a pending trigger event from an earlier statement in the SAME
        # transaction. Force the check now (harmless: it was always going to
        # pass on its own merits at commit) so B's schema build doesn't 500.
        with connection.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")

        # --- B: o MESMO serviço, chamado do jeito que o signup chama.
        result_b = provisioning.provision_tenant(
            name="Clínica Signup B",
            slug="parity-b-022",
            cnpj="22222222000102",
            owner_email="owner.parityb022@clinica.com",
            owner_full_name="Dono B",
            owner_password=None,
            host="signup.vitali.app",
            status=Tenant.Status.PENDING,
            modules=["emr", "billing"],
            create_subscription=True,
            send_welcome=True,
        )
        tenant_b = result_b.tenant

        # A ÚNICA diferença declarada é o status: o comando nasce TRIAL
        # (igual ao outro caminho de operador, TenantRegistrationView); o
        # signup nasce PENDING até o dono ativar pelo link.
        self.assertEqual(tenant_a.status, Tenant.Status.TRIAL)
        self.assertEqual(tenant_b.status, Tenant.Status.PENDING)

        state_a = _tenant_state(tenant_a)
        state_b = _tenant_state(tenant_b)
        for field in state_a.__dict__:
            self.assertEqual(
                getattr(state_a, field),
                getattr(state_b, field),
                f"{field} diverge entre comando e signup",
            )

        # Retenção: clínica recém-provisionada não ganha TenantAuditRetention
        # com purge_enabled, e o efetivo continua 240 meses / expurgo
        # desligado — para os dois caminhos (ADR-0001, ordem 021).
        for tenant in (tenant_a, tenant_b):
            self.assertFalse(TenantAuditRetention.objects.filter(tenant=tenant).exists())
            retention = _resolve_retention(tenant)
            self.assertEqual(retention.retention_months, 240)
            self.assertFalse(retention.purge_enabled)
            self.assertFalse(retention.configured)

        # Isolamento: provisionar B não alterou nada que A já tinha.
        self.assertEqual(_isolation_snapshot(tenant_a), snapshot_a)


class ProvisionTenantCommandIdempotencyTests(TestCase):
    """Reexecutar com os mesmos argumentos não cria nada; um argumento
    divergente é conflito nomeado; o token de ativação nunca vaza."""

    SLUG = "idem-022"

    def _args(self, **overrides) -> dict:
        args = {
            "slug": self.SLUG,
            "name": "Clínica Idempotente",
            "domain": "idem-022.vitali.app",
            "owner_email": "owner.idem022@clinica.com",
            "owner_name": "Dono Idem",
            "cnpj": "10101010000100",
            "modules": "emr",
        }
        args.update(overrides)
        return args

    def _call(self, *, stdout=None, **overrides):
        a = self._args(**overrides)
        return call_command(
            "provision_tenant",
            "--slug",
            a["slug"],
            "--name",
            a["name"],
            "--domain",
            a["domain"],
            "--owner-email",
            a["owner_email"],
            "--owner-name",
            a["owner_name"],
            "--cnpj",
            a["cnpj"],
            "--modules",
            a["modules"],
            stdout=stdout if stdout is not None else StringIO(),
        )

    @patch("apps.core.services.email.EmailService.send_user_invitation")
    def test_idempotent_rerun_creates_nothing_and_conflicts_are_named(self, mock_send):
        out = StringIO()
        # "apps", não o root: settings.LOGGING dá ao logger "apps" (pai de
        # apps.core.services.provisioning/invitations) propagate=False, então
        # nada dele chega no root — assertLogs(root) nunca veria nada.
        with self.assertLogs("apps", level="INFO") as captured:
            self._call(stdout=out)

        output = out.getvalue()
        self.assertIn(f"convite de ativação emitido para {self._args()['owner_email']}", output)

        # O convite de verdade carrega um token JWT (issue_password_set_
        # invitation manda o link pro EmailService, mockado aqui) — nem o
        # stdout do comando nem NENHUM log emitido durante a chamada o contêm.
        email_link = mock_send.call_args[0][1]
        token = email_link.rsplit("/", 1)[-1]
        self.assertTrue(token)
        self.assertNotIn(token, output)
        for record in captured.records:
            self.assertNotIn(token, record.getMessage())

        tenant = Tenant.objects.get(slug=self.SLUG)
        membership = UserTenantMembership.objects.get(tenant=tenant)
        subscription = Subscription.objects.get(tenant=tenant)
        self.assertEqual(Tenant.objects.filter(slug=self.SLUG).count(), 1)

        # Segunda chamada, MESMOS argumentos: não levanta, relata "já existe"
        # item a item, não cria nada (mesmos ids de membership/subscription).
        out2 = StringIO()
        self._call(stdout=out2)
        self.assertIn("já existe: tenant", out2.getvalue())
        self.assertIn("nada criado", out2.getvalue())
        self.assertEqual(Tenant.objects.filter(slug=self.SLUG).count(), 1)
        self.assertEqual(UserTenantMembership.objects.get(tenant=tenant).id, membership.id)
        self.assertEqual(Subscription.objects.get(tenant=tenant).id, subscription.id)

        # Argumento conflitante: CommandError nomeando o campo, um de cada vez.
        with self.assertRaises(CommandError) as ctx:
            self._call(owner_email="outro.dono.idem022@clinica.com")
        self.assertIn("owner_email", str(ctx.exception))

        with self.assertRaises(CommandError) as ctx:
            self._call(domain="outro-dominio-idem022.vitali.app")
        self.assertIn("domain", str(ctx.exception))

        with self.assertRaises(CommandError) as ctx:
            self._call(cnpj="99999999000199")
        self.assertIn("cnpj", str(ctx.exception))

        with self.assertRaises(CommandError) as ctx:
            self._call(name="Outro Nome Idem")
        self.assertIn("name", str(ctx.exception))

        with self.assertRaises(CommandError) as ctx:
            self._call(modules="billing")
        self.assertIn("modules", str(ctx.exception))

        # Nada mudou depois de todos os conflitos.
        self.assertEqual(Tenant.objects.filter(slug=self.SLUG).count(), 1)
        self.assertEqual(UserTenantMembership.objects.get(tenant=tenant).id, membership.id)
        self.assertEqual(Subscription.objects.get(tenant=tenant).id, subscription.id)
        tenant.refresh_from_db()
        self.assertEqual(tenant.name, self._args()["name"])


class ProvisionTenantCommandRollbackTests(TestCase):
    """Domínio/e-mail de outro tenant é conflito nomeado; o mesmo slug com
    dados divergentes não toca o tenant existente; uma falha forçada após o
    schema derruba só a clínica nova."""

    def test_conflicts_and_rollback_never_touch_a_pre_existing_tenant(self):
        # A: clínica cheia de dado (domínio, dono, membership, assinatura,
        # flags, partições) — o alvo que NADA abaixo pode alcançar.
        call_command(
            "provision_tenant",
            "--slug",
            "full-c-022",
            "--name",
            "Clínica Cheia",
            "--domain",
            "full-c-022.vitali.app",
            "--owner-email",
            "owner.fullc022@clinica.com",
            "--owner-name",
            "Dono Cheio",
            "--modules",
            "emr,billing",
            stdout=StringIO(),
        )
        tenant_a = Tenant.objects.get(slug="full-c-022")
        snapshot = _isolation_snapshot(tenant_a)

        # Domínio que já pertence a A: CommandError nomeado, nada criado.
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "provision_tenant",
                "--slug",
                "domain-conflict-022",
                "--name",
                "Outra Clínica",
                "--domain",
                "full-c-022.vitali.app",  # já é de A
                "--owner-email",
                "owner.domainconflict022@clinica.com",
                "--owner-name",
                "Outro Dono",
            )
        self.assertIn("domínio", str(ctx.exception))
        self.assertFalse(Tenant.objects.filter(slug="domain-conflict-022").exists())

        # E-mail de dono que já pertence a A: idem.
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "provision_tenant",
                "--slug",
                "email-conflict-022",
                "--name",
                "Outra Clínica 2",
                "--domain",
                "email-conflict-022.vitali.app",
                "--owner-email",
                "owner.fullc022@clinica.com",  # já é de A
                "--owner-name",
                "Outro Dono 2",
            )
        self.assertIn("e-mail", str(ctx.exception).lower())
        self.assertFalse(Tenant.objects.filter(slug="email-conflict-022").exists())

        # Mesmo slug de A, tudo mais diferente: o atalho do comando (slug já
        # existe) nem chama provision_tenant() — nomeia CADA campo divergente
        # e não toca em A.
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "provision_tenant",
                "--slug",
                "full-c-022",
                "--name",
                "Nome Errado",
                "--domain",
                "outro-dominio-022.vitali.app",
                "--owner-email",
                "outro.dono.022@clinica.com",
                "--owner-name",
                "Outro Dono 3",
            )
        message = str(ctx.exception)
        self.assertIn("name", message)
        self.assertIn("domain", message)
        self.assertIn("owner_email", message)
        self.assertEqual(_isolation_snapshot(tenant_a), snapshot)

        # O MESMO conflito de slug, mas no nível do SERVIÇO (não só o atalho
        # do comando): um IntegrityError de slug duplicado nunca chega perto
        # de A porque acontece ANTES do tenant.save() ter sucesso — não há
        # nada para _drop_tenant alcançar.
        with self.assertRaises(provisioning.ProvisioningConflict):
            provisioning.provision_tenant(
                name="Clínica Duplicada",
                slug=tenant_a.slug,
                cnpj="",
                owner_email="novo.dono.dup022@clinica.com",
                owner_full_name="Novo Dono",
                owner_password=None,
                host="dup-022.vitali.app",
                create_subscription=False,
                send_welcome=False,
            )
        self.assertEqual(_isolation_snapshot(tenant_a), snapshot)

        # A's owner User INSERT still carries a pending deferred FK check in
        # this same open transaction (see the identical comment in
        # ProvisionTenantCommandParityTests) — clear it before building
        # ANOTHER real schema below, or that build 500s for an unrelated
        # reason and this test would fail for the wrong one.
        with connection.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL IMMEDIATE")

        # Rollback de verdade: falha forçada DEPOIS do schema (na criação da
        # assinatura), numa clínica NOVA — ela some por inteiro (tenant row E
        # schema PG), e A permanece intocada.
        with patch(
            "apps.core.services.provisioning._create_trial_subscription",
            side_effect=RuntimeError("falha forçada — teste de rollback"),
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "provision_tenant",
                    "--slug",
                    "rollback-d-022",
                    "--name",
                    "Clínica Que Não Deveria Sobreviver",
                    "--domain",
                    "rollback-d-022.vitali.app",
                    "--owner-email",
                    "owner.rollbackd022@clinica.com",
                    "--owner-name",
                    "Dono D",
                )
        self.assertFalse(Tenant.objects.filter(slug="rollback-d-022").exists())
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", ["rollback-d-022"])
            self.assertIsNone(cur.fetchone(), "schema rollback-d-022 não foi derrubado")
        self.assertEqual(_isolation_snapshot(tenant_a), snapshot)


class ProvisionTenantCommandParserTests(TestCase):
    """O parser recusa argumento de senha, e módulo desconhecido é rejeitado
    antes de qualquer provisionamento — nenhum destes constrói schema real."""

    def _base_args(self) -> list[str]:
        return [
            "--slug",
            "parser-022",
            "--name",
            "Parser Clínica",
            "--domain",
            "parser-022.vitali.app",
            "--owner-email",
            "owner.parser022@clinica.com",
            "--owner-name",
            "Dono Parser",
        ]

    def test_parser_rejects_any_password_argument(self):
        for flag in ("--password", "--owner-password", "--senha", "--pass"):
            with self.assertRaises(CommandError, msg=flag):
                call_command("provision_tenant", *self._base_args(), flag, "x")
        self.assertFalse(Tenant.objects.filter(slug="parser-022").exists())

    def test_unknown_module_is_rejected_before_any_provisioning(self):
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "provision_tenant", *self._base_args(), "--modules", "nao_existe_esse_modulo"
            )
        self.assertIn("nao_existe_esse_modulo", str(ctx.exception))
        self.assertFalse(Tenant.objects.filter(slug="parser-022").exists())
