"""
Ordem 022 — a clínica nova nasce com partição de auditoria, e o laço de
``ensure_audit_partitions`` isola falha por tenant.

Duas hipóteses lidas do código (021/020), confirmadas na lab (ver o commit
vermelho ``313cff7``) e agora fechadas pelo conserto:

1. ``services.provisioning.provision_tenant`` (o mesmo caminho que o signup e
   o comando ``manage.py provision_tenant`` usam) agora garante a folha
   dedicada do mês corrente e do seguinte logo depois do schema. Uma escrita
   real de ``AuditLog`` pelo ORM, sem rodar ``ensure_audit_partitions`` antes,
   cai na folha DEDICADA do mês, não na DEFAULT.

2. ``ensure_audit_partitions`` isola cada (tenant, mês) num savepoint próprio:
   uma clínica com linha na DEFAULT do mês corrente ainda faz
   ``ensure_tenant_partition`` levantar ``IntegrityError`` para ELA, mas isso
   não aborta o comando inteiro — os demais tenants ganham suas folhas de
   qualquer jeito, e o comando termina com ``CommandError`` nomeando quem
   falhou e apontando ``backfill_audit_partitions``.

Nenhum dos dois testes prepara a condição medida com SQL cru (lição da
ordem 021: teste que constrói à mão a condição medida mede a si mesmo).
"""

from __future__ import annotations

import datetime
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django_tenants.utils import schema_context

from apps.core import partitioning
from apps.core.models import AuditLog, Tenant
from apps.core.services import provisioning


def _next_month(for_date: datetime.date) -> datetime.date:
    return (
        datetime.date(for_date.year + 1, 1, 1)
        if for_date.month == 12
        else datetime.date(for_date.year, for_date.month + 1, 1)
    )


def _fast_tenant(schema_name: str) -> Tenant:
    """A Tenant row without a real PG schema (cheap — item 2 never touches
    the tenant's own schema, only the shared ``core_auditlog`` table, see
    its model docstring)."""
    tenant = Tenant(name=schema_name, slug=schema_name)
    tenant.auto_create_schema = False
    tenant.save()
    return tenant


class ProvisionTenantAuditPartitionTests(TestCase):
    """Item 1: a clínica nova nasce com partição de auditoria."""

    def test_orm_write_after_real_provisioning_lands_in_dedicated_leaf(self):
        result = provisioning.provision_tenant(
            name="Clinica Particao 022",
            slug="clinica-particao-022",
            cnpj=None,
            owner_email="owner.particao022@clinica.com",
            owner_full_name="Dono Particao",
            owner_password="Str0ngPassw0rd!022",
            host="localhost",
            create_subscription=False,
            send_welcome=False,
        )
        tenant = result.tenant

        with schema_context(tenant.schema_name):
            log = AuditLog.objects.create(
                action="login", resource_type="user", resource_id="provision-partition-1"
            )

        today = datetime.date.today()
        expected_leaf = partitioning.tenant_partition_name(
            partitioning.month_partition_name(today), tenant.schema_name
        )
        with connection.cursor() as cur:
            cur.execute(
                "SELECT tableoid::regclass::text FROM core_auditlog WHERE id = %s", [log.id]
            )
            actual_leaf = cur.fetchone()[0]
        self.assertEqual(actual_leaf, expected_leaf)

        next_month_leaf = partitioning.tenant_partition_name(
            partitioning.month_partition_name(_next_month(today)), tenant.schema_name
        )
        self.assertTrue(
            partitioning.partition_exists(next_month_leaf),
            f"missing next month's dedicated leaf {next_month_leaf}",
        )


class EnsureAuditPartitionsLoopIsolationTests(TestCase):
    """Item 2: uma clínica com linha na DEFAULT do mês não pode derrubar as
    demais no laço do comando — nem quem vem antes, nem quem vem depois."""

    def test_default_leaf_conflict_does_not_starve_the_other_tenants(self):
        problematic = _fast_tenant("problem-022")
        second = _fast_tenant("second-022")
        third = _fast_tenant("third-022")

        today = datetime.date.today()
        # Estado normal de deploy: a folha do MÊS (sem folha dedicada por
        # tenant) já existe quando a clínica nova escreve sua primeira linha.
        partitioning.ensure_month_partition(today)

        with schema_context(problematic.schema_name):
            AuditLog.objects.create(
                action="login", resource_type="user", resource_id="collision-022-1"
            )

        out = StringIO()
        err = StringIO()
        with self.assertRaises(CommandError) as ctx:
            call_command("ensure_audit_partitions", stdout=out, stderr=err)

        message = str(ctx.exception)
        self.assertIn(problematic.schema_name, message)
        self.assertIn("backfill_audit_partitions", message)

        # Não dependemos da ordem do laço (que agora é determinística —
        # order_by("schema_name") — mas isso é um detalhe de implementação
        # que este teste não deveria precisar conhecer): TODOS os outros
        # tenants ganham as duas folhas, estejam antes ou depois do
        # problemático em qualquer ordenação possível.
        next_month = _next_month(today)
        for tenant in (second, third):
            for month_date in (today, next_month):
                leaf = partitioning.tenant_partition_name(
                    partitioning.month_partition_name(month_date), tenant.schema_name
                )
                self.assertTrue(
                    partitioning.partition_exists(leaf),
                    f"{tenant.schema_name} deveria ter ganhado {leaf} mesmo com o vizinho quebrado",
                )
