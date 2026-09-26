"""
Ordem 022, passo 0 — teste vermelho antes do conserto.

Duas hipóteses lidas do código (021/020) e ainda não provadas:

1. Nenhum caminho de criação de tenant chama ``ensure_tenant_partition``.
   Provisionar uma clínica pelo caminho real (``services.provisioning.
   provision_tenant``, o mesmo que o signup usa) e escrever um ``AuditLog``
   pelo ORM logo em seguida, sem rodar ``ensure_audit_partitions`` antes,
   deveria cair na folha DEDICADA do mês — hoje cai na DEFAULT.

2. ``ensure_audit_partitions`` percorre os tenants num laço sem isolar falha
   por tenant. Uma clínica com linha na DEFAULT do mês corrente faz
   ``ensure_tenant_partition`` levantar ``IntegrityError`` ao tentar anexar a
   folha dedicada — e hoje isso aborta o comando inteiro, deixando sem folha
   os tenants que ainda não tinham sido processados no laço.

Nenhum dos dois testes prepara a condição medida com SQL cru (lição da
ordem 021: teste que constrói à mão a condição medida mede a si mesmo).
"""

from __future__ import annotations

import datetime
from io import StringIO

from django.core.management import call_command
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
    demais no laço do comando."""

    def test_default_leaf_conflict_does_not_starve_the_other_tenants(self):
        problematic = _fast_tenant("problem-022")
        _fast_tenant("second-022")
        _fast_tenant("third-022")

        today = datetime.date.today()
        # Estado normal de deploy: a folha do MÊS (sem folha dedicada por
        # tenant) já existe quando a clínica nova escreve sua primeira linha.
        partitioning.ensure_month_partition(today)

        with schema_context(problematic.schema_name):
            AuditLog.objects.create(
                action="login", resource_type="user", resource_id="collision-022-1"
            )

        # Não presumimos a ordem do laço: consultamos a MESMA queryset que o
        # comando usa e usamos a ordem observada para saber quem "vem depois".
        ordered = list(Tenant.objects.exclude(schema_name="public"))
        ordered_names = [t.schema_name for t in ordered]
        self.assertIn(problematic.schema_name, ordered_names)
        idx = ordered_names.index(problematic.schema_name)
        tenants_after = ordered[idx + 1 :]
        self.assertTrue(
            tenants_after,
            f"cenário precisa de ao menos um tenant depois do problemático; ordem real={ordered_names}",
        )

        out = StringIO()
        err = StringIO()
        raised = None
        try:
            call_command("ensure_audit_partitions", stdout=out, stderr=err)
        except Exception as exc:  # noqa: BLE001 — queremos inspecionar qualquer forma de falha
            raised = exc

        self.assertIsNotNone(
            raised, "esperava que o comando terminasse com erro (clínica com linha na DEFAULT)"
        )
        message = str(raised)
        self.assertIn(problematic.schema_name, message)
        self.assertIn("backfill_audit_partitions", message)

        next_month = _next_month(today)
        for tenant in tenants_after:
            for month_date in (today, next_month):
                leaf = partitioning.tenant_partition_name(
                    partitioning.month_partition_name(month_date), tenant.schema_name
                )
                self.assertTrue(
                    partitioning.partition_exists(leaf),
                    f"{tenant.schema_name} deveria ter ganhado {leaf} mesmo com o vizinho quebrado",
                )
