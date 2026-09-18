"""Ordem 018 — amarra `?employee=` (o parâmetro que filtra) a `AUDIT_LIST_PARAMS`
(o parâmetro que a 017 declarou na trilha) para as quatro views de RH com trilha
de leitura: `LeaveRequestViewSet`, `OccupationalHealthExamViewSet`,
`DependentViewSet` e `TimeEntryViewSet`.

A 017 pôs `AUDIT_LIST_PARAMS = ()` nas três primeiras porque `?employee=` não
filtrava nada nelas — registrar o critério seria trilha falsa. Esta ordem liga
o filtro e devolve `AUDIT_LIST_PARAMS = ("employee",)`. O teste que amarra as
duas coisas: se o parâmetro voltar a ser ignorado pela query (regressão de
`get_queryset`) ou a trilha voltar a `()` (regressão do mixin), este arquivo
fica vermelho.

Cada classe abaixo, com dois funcionários e um registro de cada:
  * `GET ...?employee=<A>` devolve SÓ o registro de A;
  * a mesma chamada grava EXATAMENTE UMA linha de AuditLog
    `view_record_list` com o critério em `new_data`;
  * `GET` sem parâmetro grava EXATAMENTE UMA linha, com `new_data={}`
    (correção pós-019, `AUDIT_LIST_ALWAYS` — ver
    `test_unfiltered_list_now_logs_the_whole_roster`; a 017 tinha fixado o
    oposto, "não grava", porque `?employee=` era inerte então e registrar o
    critério seria mentira — a 018 ligou o filtro, e ler o quadro inteiro
    sem filtro passou a ser MAIS exposição, não menos).

Rodada de correção pós-revisão: `?employee=` malformado virava 500 (o
exception handler padrão do DRF não traduz `django.core.exceptions.
ValidationError`) — as três views novas herdaram esse defeito do
`TimeEntryViewSet`, que já o tinha antes da 017. Três casos de borda cobrem
a correção (`EmployeeFilteredQuerysetMixin` em `apps/hr/views.py`), também
para as quatro:
  * `?employee=<não-uuid>` → 400, e zero `AuditLog` (a exceção corta o
    `list()` do `AuditReadMixin` antes de ele gravar);
  * `?employee=<uuid válido inexistente>` → 200, lista vazia, MAS grava
    trilha — a busca é o fato que importa, não a resposta vazia;
  * `?employee=A&employee=B` (repetido) → o que filtra e o que a trilha
    registra têm que concordar em qual dos dois venceu.
"""

import uuid
from datetime import date

from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role, User
from apps.hr.models import Dependent, Employee, LeaveRequest, OccupationalHealthExam, TimeEntry
from apps.test_utils import TenantTestCase


class _EmployeeFilterAuditMixin:
    """Mixin comum às quatro views: dois funcionários, um registro de cada.

    Deliberadamente NÃO herda de ``TestCase`` — só mixin, subclasses é que
    combinam com ``TenantTestCase`` (ver as quatro classes abaixo). Assim
    pytest/unittest nunca coletam este bloco como um caso de teste por si só
    (ele não tem `_make_record`/`endpoint` reais, só o contrato).

    Subclasses só precisam fixar `endpoint`, `audit_resource_type` e
    `_make_record`.
    """

    endpoint: str = ""
    audit_resource_type: str = ""

    def setUp(self):
        super().setUp()
        self.hr_role = Role.objects.create(name="rh-filtro", permissions=["hr.manage"])
        self.manager = User.objects.create_user(
            email="gestora@filtro.test", password="pw", full_name="Gestora RH", role=self.hr_role
        )
        user_a = User.objects.create_user(
            email="func-a@filtro.test", password="pw", full_name="Funcionária A"
        )
        user_b = User.objects.create_user(
            email="func-b@filtro.test", password="pw", full_name="Funcionário B"
        )
        self.employee_a = Employee.objects.create(
            user=user_a, hire_date=date(2026, 1, 1), contract_type="clt"
        )
        self.employee_b = Employee.objects.create(
            user=user_b, hire_date=date(2026, 1, 1), contract_type="clt"
        )
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        self.client.force_authenticate(self.manager)
        self.record_a = self._make_record(self.employee_a)
        self.record_b = self._make_record(self.employee_b)

    def _make_record(self, employee):  # pragma: no cover - overridden per subclass
        raise NotImplementedError

    def _list(self, **params):
        return self.client.get(self.endpoint, params)

    def _ids(self, response):
        return {row["id"] for row in response.json()["results"]}

    def test_employee_param_filters_to_only_that_employee(self):
        response = self._list(employee=str(self.employee_a.id))
        assert response.status_code == 200, response.content
        assert self._ids(response) == {str(self.record_a.id)}

    def test_employee_param_logs_exactly_one_audit_entry_with_criterion(self):
        response = self._list(employee=str(self.employee_a.id))
        assert response.status_code == 200, response.content
        logs = AuditLog.objects.filter(
            action="view_record_list", resource_type=self.audit_resource_type
        )
        assert logs.count() == 1
        assert logs.get().new_data == {"employee": str(self.employee_a.id)}

    def test_unfiltered_list_now_logs_the_whole_roster(self):
        """Decisão mudou (correção pós-ordem 019, `AUDIT_LIST_ALWAYS`).

        Esta asserção era "lista sem filtro não grava" — certa NO MOMENTO em
        que `?employee=` era inerte nestas quatro views (017) e registrar o
        critério seria mentira. A 018 ligou o filtro de verdade; a correção
        pós-019 reconheceu que a decisão original não fazia mais sentido: ler
        o quadro INTEIRO de afastamentos/exames/dependentes/pontos de uma
        clínica é MAIS exposição que ler o de uma pessoa, não menos — e o
        caso concreto que motivou a mudança é exatamente este:
        `frontend/app/(dashboard)/rh/afastamentos/page.tsx` chama
        `/api/v1/hr/leave-requests/` sem `?employee=`, e cada abertura de tela
        lia o afastamento médico do quadro inteiro sem deixar rastro nenhum.
        `AUDIT_LIST_ALWAYS = True` nestas quatro views (`apps/hr/views.py`)
        fecha esse buraco: `list` sem filtro grava `view_record_list` com
        `new_data={}` — sem critério porque não houve busca dirigida, mas COM
        rastro porque o rol inteiro foi lido.
        """
        response = self._list()
        assert response.status_code == 200, response.content
        assert self._ids(response) == {str(self.record_a.id), str(self.record_b.id)}
        logs = AuditLog.objects.filter(
            action="view_record_list", resource_type=self.audit_resource_type
        )
        assert logs.count() == 1
        assert logs.get().new_data == {}

    def test_malformed_employee_param_returns_400_and_does_not_log(self):
        response = self._list(employee="not-a-uuid")
        assert response.status_code == 400, response.content
        assert not AuditLog.objects.filter(
            action="view_record_list", resource_type=self.audit_resource_type
        ).exists()

    def test_valid_but_nonexistent_employee_returns_empty_list_and_still_logs(self):
        missing = str(uuid.uuid4())
        response = self._list(employee=missing)
        assert response.status_code == 200, response.content
        assert self._ids(response) == set()
        logs = AuditLog.objects.filter(
            action="view_record_list", resource_type=self.audit_resource_type
        )
        assert logs.count() == 1
        assert logs.get().new_data == {"employee": missing}

    def test_repeated_employee_param_filter_and_audit_agree_on_last_value(self):
        # QueryDict semântica: valor repetido → o ÚLTIMO vence, tanto para
        # `.get(...)` (usado pelo filtro em `_employee_filter_value`) quanto
        # para `request.query_params[...]` (usado por `AuditReadMixin.list`
        # ao montar `new_data`). Trava que os dois lados concordam — um
        # refator que troque um dos dois para `getlist()` tem que reprovar.
        response = self.client.get(
            self.endpoint, {"employee": [str(self.employee_a.id), str(self.employee_b.id)]}
        )
        assert response.status_code == 200, response.content
        assert self._ids(response) == {str(self.record_b.id)}
        logs = AuditLog.objects.filter(
            action="view_record_list", resource_type=self.audit_resource_type
        )
        assert logs.count() == 1
        assert logs.get().new_data == {"employee": str(self.employee_b.id)}


class LeaveRequestEmployeeFilterAuditTests(_EmployeeFilterAuditMixin, TenantTestCase):
    endpoint = "/api/v1/hr/leave-requests/"
    audit_resource_type = "leave_request"

    def _make_record(self, employee):
        return LeaveRequest.objects.create(
            employee=employee,
            leave_type=LeaveRequest.Type.VACATION,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 10),
            requested_by=self.manager,
        )


class OccupationalHealthExamEmployeeFilterAuditTests(_EmployeeFilterAuditMixin, TenantTestCase):
    endpoint = "/api/v1/hr/occupational-health-exams/"
    audit_resource_type = "occupational_health_exam"

    def _make_record(self, employee):
        return OccupationalHealthExam.objects.create(
            employee=employee,
            exam_type="periodic",
            performed_on=date(2026, 7, 1),
            result="fit",
            provider_name="Clínica Ocupacional",
            recorded_by=self.manager,
        )


class DependentEmployeeFilterAuditTests(_EmployeeFilterAuditMixin, TenantTestCase):
    endpoint = "/api/v1/hr/dependents/"
    audit_resource_type = "dependent"

    def _make_record(self, employee):
        return Dependent.objects.create(
            employee=employee,
            full_name=f"Dependente de {employee.user.full_name}",
            relationship="child",
        )


class TimeEntryEmployeeFilterAuditTests(_EmployeeFilterAuditMixin, TenantTestCase):
    """`TimeEntryViewSet` já filtrava e já tinha `AUDIT_LIST_PARAMS = ("employee",)`
    antes desta ordem (017) — esta classe prova que continua valendo, e cobre
    a quarta das "quatro views de RH com trilha" que a ordem pede.
    """

    endpoint = "/api/v1/hr/time-entries/"
    audit_resource_type = "time_entry"

    def _make_record(self, employee):
        return TimeEntry.objects.create(
            employee=employee,
            event_type="in",
            occurred_at=timezone.now(),
            recorded_by=self.manager,
        )
