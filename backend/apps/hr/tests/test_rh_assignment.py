"""S2-T1 — Position (cargo), EmployeeAssignment (lotação), Dependent tests."""

from datetime import date

from django.db import IntegrityError, transaction

from apps.core.models import User
from apps.hr.models import Dependent, Employee, EmployeeAssignment, Position
from apps.hr.services import AssignmentService
from apps.organization.models import CostCenter, Facility, LegalEntity, OrganizationalUnit
from apps.test_utils import TenantTestCase


def _employee(email="emp@clinic.test", name="Worker One"):
    user = User.objects.create_user(email=email, password="pw", full_name=name)
    return Employee.objects.create(user=user, hire_date=date(2026, 1, 1), contract_type="clt")


def _unit(code="U-1", name="Enfermaria"):
    entity = LegalEntity.objects.create(code=f"LE-{code}", name="Entidade")
    facility = Facility.objects.create(code=f"FAC-{code}", name="Clínica", legal_entity=entity)
    return OrganizationalUnit.objects.create(code=code, name=name, facility=facility)


class PositionTests(TenantTestCase):
    def test_position_str_and_defaults(self):
        pos = Position.objects.create(title="Enfermeiro", cbo="2235-05")
        assert pos.active is True
        assert pos.cbo == "2235-05"  # plain CharField for now (S1 FK pending)
        assert "Enfermeiro" in str(pos)


class EmployeeAssignmentTests(TenantTestCase):
    def test_assign_employee_to_unit_with_vigency(self):
        employee = _employee()
        unit = _unit()
        cc = CostCenter.objects.create(
            code="CC-1", name="Centro", legal_entity=unit.facility.legal_entity
        )
        assignment = AssignmentService.assign(
            employee=employee,
            unit=unit,
            cost_center=cc,
            role="Enfermeiro assistencial",
            start_date=date(2026, 2, 1),
        )
        assert assignment.active is True
        assert assignment.unit_id == unit.id
        assert assignment.cost_center_id == cc.id
        assert employee.assignments.filter(active=True).count() == 1

    def test_only_one_active_assignment_per_employee(self):
        employee = _employee()
        unit_a = _unit(code="U-A", name="A")
        unit_b = _unit(code="U-B", name="B")
        first = AssignmentService.assign(
            employee=employee, unit=unit_a, start_date=date(2026, 2, 1)
        )
        second = AssignmentService.assign(
            employee=employee, unit=unit_b, start_date=date(2026, 3, 1)
        )
        first.refresh_from_db()
        assert first.active is False
        assert first.end_date is not None
        assert second.active is True
        assert employee.assignments.filter(active=True).count() == 1

    def test_second_active_assignment_db_constraint(self):
        employee = _employee()
        unit = _unit()
        EmployeeAssignment.objects.create(
            employee=employee, unit=unit, start_date=date(2026, 2, 1), active=True
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EmployeeAssignment.objects.create(
                    employee=employee, unit=unit, start_date=date(2026, 3, 1), active=True
                )

    def test_assignment_vigency_order_guarded(self):
        employee = _employee()
        unit = _unit()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EmployeeAssignment.objects.create(
                    employee=employee,
                    unit=unit,
                    start_date=date(2026, 3, 1),
                    end_date=date(2026, 2, 1),
                    active=False,
                )


class DependentTests(TenantTestCase):
    def test_dependents_of_employee(self):
        employee = _employee()
        Dependent.objects.create(
            employee=employee, full_name="Filho", relationship="child", birth_date=date(2020, 5, 1)
        )
        Dependent.objects.create(employee=employee, full_name="Cônjuge", relationship="spouse")
        assert employee.dependents.count() == 2
        assert set(employee.dependents.values_list("relationship", flat=True)) == {
            "child",
            "spouse",
        }
