"""
Ordem 028 — migration de dados: DoseRule.validated (bool) → status_validacao.

Testa a FUNÇÃO de dados da migration
(``apps/pharmacy/migrations/0033_..._and_more.py::report_demoted_rules``) em
isolamento, sem MigrationExecutor: reconstruir o estado histórico do projeto
inteiro (centenas de migrations, muitos apps) para uma reversão+reaplicação
real custa minutos de CPU pura por chamada — pesado demais para o que este
teste precisa provar. ``report_demoted_rules`` só lê ``DoseRule.objects.filter
(validated=True).count()`` e imprime; um dublê mínimo de ``apps``/
``schema_editor`` basta (minimiza schema real, como pedido).

O comportamento de dado em si (toda linha nasce ``nao_validado`` porque
``status_validacao`` tem ``default=...NAO_VALIDADO``, mesmo para uma linha que
era ``validated=True``) é gravado no próprio ``AddField`` do Django — não há
lógica de escrita nesta função além do print; o que se prova aqui é que a
contagem e a mensagem por schema saem certas.
"""

import importlib
import io
from contextlib import redirect_stdout

from django.test import SimpleTestCase

_MIGRATION_MODULE = (
    "apps.pharmacy.migrations.0033_remove_doserule_validated_doserule_fonte_ref_and_more"
)


class _FakeQuerySet:
    def __init__(self, count: int):
        self._count = count

    def filter(self, **kwargs):
        return self

    def count(self) -> int:
        return self._count


class _FakeDoseRuleManager:
    objects = None

    def __init__(self, count: int):
        self.objects = _FakeQuerySet(count)


class _FakeHistoricalApps:
    """Stand-in for the migration's historical ``apps`` — only ``get_model``
    is used by ``report_demoted_rules``."""

    def __init__(self, demoted_count: int):
        self._model = _FakeDoseRuleManager(demoted_count)

    def get_model(self, app_label: str, name: str):
        assert (app_label, name) == ("pharmacy", "DoseRule")
        return self._model


class _FakeConnection:
    def __init__(self, schema_name: str):
        self.schema_name = schema_name


class _FakeSchemaEditor:
    def __init__(self, schema_name: str):
        self.connection = _FakeConnection(schema_name)


class ReportDemotedRulesTest(SimpleTestCase):
    """Unit test of the migration's data function — no real schema touched."""

    def test_reports_the_count_and_schema_name(self):
        report_demoted_rules = importlib.import_module(_MIGRATION_MODULE).report_demoted_rules

        fake_apps = _FakeHistoricalApps(demoted_count=3)
        fake_schema_editor = _FakeSchemaEditor(schema_name="acme_test")

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            report_demoted_rules(fake_apps, fake_schema_editor)

        output = buffer.getvalue()
        self.assertIn("3 regra(s) validada(s) voltaram a nao_validado", output)
        self.assertIn("acme_test", output)

    def test_reverse_is_a_noop(self):
        """The reverse operation is ``migrations.RunPython.noop`` — reversing
        this migration must not attempt to resurrect the old boolean value."""
        from django.db import migrations

        module = importlib.import_module(_MIGRATION_MODULE)
        run_python_op = next(
            op for op in module.Migration.operations if isinstance(op, migrations.RunPython)
        )
        self.assertIs(run_python_op.reverse_code, migrations.RunPython.noop)

    def test_addfield_default_is_nao_validado(self):
        """The safety property this migration relies on: `status_validacao`'s
        AddField defaults EVERY row (old validated=True included) to
        nao_validado — that default IS the "no historical validation has a
        CRF on file" rule; `report_demoted_rules` only narrates it."""
        from django.db import migrations

        from apps.pharmacy.models import DoseRule

        module = importlib.import_module(_MIGRATION_MODULE)
        add_status = next(
            op
            for op in module.Migration.operations
            if isinstance(op, migrations.AddField) and op.name == "status_validacao"
        )
        self.assertEqual(add_status.field.default, DoseRule.StatusValidacao.NAO_VALIDADO)
