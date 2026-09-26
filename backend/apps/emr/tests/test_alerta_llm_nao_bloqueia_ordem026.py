"""
Ordem 026 — alerta de LLM não bloqueia o gate, e override de dose e alergia
deixa trilha.

INTENT v6: "motor determinístico autoritativo; o LLM só explica", and every
AI wedge is a soft-stop with an AUDITED override.

* The LLM task (apps.emr.tasks.check_prescription_safety) upserted
  AISafetyAlert by (prescription_item, alert_type) WITHOUT ``source``. With an
  engine row of the same type on the item, it rewrote the engine's verdict:
  wiped an acknowledged override back to "flagged", or turned the engine row
  into a blocking contraindication — the LLM deciding the sign/dispense gate.
* Acknowledging a dose/allergy alert wrote no AuditLog (only a logger line),
  unlike the glosa override (glosa_alert_overridden, ordem 007).
"""

import ast
import datetime
import pathlib
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.test_utils import TenantTestCase


class _PrescriptionFixture:
    def _build(self):
        from django.contrib.auth import get_user_model

        from apps.core.models import FeatureFlag, Role
        from apps.emr.models import (
            Encounter,
            Patient,
            Prescription,
            PrescriptionItem,
            Professional,
        )
        from apps.pharmacy.models import Drug

        cache.clear()
        tenant = self.__class__.tenant
        for key in ("dose_safety", "allergy_safety"):
            FeatureFlag.objects.update_or_create(
                tenant=tenant, module_key=key, defaults={"is_enabled": True}
            )
        role = Role.objects.create(
            name="medico-026", permissions=["emr.read", "emr.write", "emr.sign"]
        )
        self.user = get_user_model().objects.create_user(
            email="medico.026@clinica.test",
            password="Medico!026#x",
            full_name="Médica 026",
            role=role,
        )
        professional = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="260260", council_state="SP"
        )
        patient = Patient.objects.create(
            full_name="Paciente 026",
            cpf="390.533.447-05",
            birth_date=datetime.date(1960, 2, 2),
            gender="F",
        )
        encounter = Encounter.objects.create(
            patient=patient, professional=professional, encounter_date=timezone.now()
        )
        self.prescription = Prescription.objects.create(
            encounter=encounter, patient=patient, prescriber=professional
        )
        drug = Drug.objects.create(
            name="Varfarina 5mg", generic_name="varfarina", controlled_class="none"
        )
        self.item = PrescriptionItem.objects.create(
            prescription=self.prescription,
            drug=drug,
            generic_name="varfarina",
            quantity=1,
            unit_of_measure="cx",
        )

    def _engine_alert(self, **fields):
        from apps.emr.models import AISafetyAlert

        values = {
            "alert_type": "dose",
            "severity": "contraindication",
            "message": "Dose acima do máximo do formulário",
            "status": "flagged",
        }
        values.update(fields)
        return AISafetyAlert.objects.create(
            prescription_item=self.item, source=AISafetyAlert.Source.ENGINE, **values
        )

    def _run_llm_task(self, alert_type, severity):
        from apps.emr.services.prescription_safety import SafetyAlert, SafetyResult
        from apps.emr.tasks import check_prescription_safety

        llm_result = SafetyResult(
            is_safe=False,
            alerts=[SafetyAlert(alert_type=alert_type, severity=severity, message="LLM diz")],
        )
        with patch(
            "apps.emr.services.prescription_safety.PrescriptionSafetyChecker.check",
            return_value=llm_result,
        ):
            check_prescription_safety(str(self.item.id))


class LLMDoesNotRewriteTheEngineTest(_PrescriptionFixture, TenantTestCase):
    def setUp(self):
        self._build()

    def test_acknowledged_engine_override_survives_the_llm(self):
        engine = self._engine_alert()
        engine.acknowledge(self.user, "Paciente com dose ajustada pelo hematologista")

        self._run_llm_task("dose", "caution")

        engine.refresh_from_db()
        self.assertEqual(engine.status, "acknowledged")
        self.assertEqual(engine.severity, "contraindication")
        self.assertEqual(engine.override_reason, "Paciente com dose ajustada pelo hematologista")

    def test_an_llm_contraindication_does_not_decide_the_gate(self):
        from apps.emr.models import AISafetyAlert
        from apps.emr.services.prescription_safety_gate import has_blocking_safety_alert

        engine = self._engine_alert(severity="caution")  # engine: advise, not a block
        self.assertFalse(has_blocking_safety_alert(self.prescription))

        self._run_llm_task("dose", "contraindication")

        engine.refresh_from_db()
        self.assertEqual(engine.severity, "caution")
        self.assertFalse(has_blocking_safety_alert(self.prescription))
        # The LLM's opinion is kept — on its own row.
        self.assertTrue(
            AISafetyAlert.objects.filter(
                prescription_item=self.item,
                alert_type="dose",
                source=AISafetyAlert.Source.LLM,
                severity="contraindication",
            ).exists()
        )


class OverrideLeavesATrailTest(_PrescriptionFixture, TenantTestCase):
    def setUp(self):
        self._build()
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _override(self, alert, reason):
        return self.client.post(
            f"/api/v1/safety-alerts/{alert.id}/acknowledge/", {"reason": reason}, format="json"
        )

    def _assert_trail(self, alert, action, reason):
        from apps.core.models import AuditLog

        # Same shape as glosa_alert_overridden: the resource is what the alert
        # is about (the prescription item); the alert itself is in new_data.
        rows = AuditLog.objects.filter(
            action=action,
            resource_type="prescription_item",
            resource_id=str(alert.prescription_item_id),
        )
        self.assertEqual(rows.count(), 1, f"nenhum AuditLog {action} para o override")
        row = rows.get()
        self.assertEqual(row.user_id, self.user.id)
        self.assertEqual(row.schema_name, self.__class__.tenant.schema_name)
        self.assertEqual(row.old_data, {"status": "flagged"})
        self.assertEqual(row.new_data["alert_id"], str(alert.id))
        self.assertEqual(row.new_data["override_reason"], reason)
        self.assertEqual(row.new_data["alert_type"], alert.alert_type)
        self.assertEqual(row.new_data["severity"], alert.severity)

    def test_dose_override_is_audited(self):
        alert = self._engine_alert(alert_type="dose", severity="caution")
        reason = "Dose de ataque prescrita pelo cardiologista"
        self.assertEqual(self._override(alert, reason).status_code, 200)
        self._assert_trail(alert, "dose_alert_overridden", reason)

    def test_allergy_override_is_audited(self):
        alert = self._engine_alert(
            alert_type="allergy", severity="contraindication", message="Alergia a cumarínicos"
        )
        reason = "Teste de provocação negativo documentado em 2024"
        self.assertEqual(self._override(alert, reason).status_code, 200)
        self._assert_trail(alert, "allergy_alert_overridden", reason)


class EveryAISafetyAlertUpsertFixesSourceTest(TenantTestCase):
    """Guard: the next generator must not repeat the clobber."""

    def test_upserts_of_aisafetyalert_name_their_source(self):
        apps_dir = pathlib.Path(__file__).resolve().parents[2]
        offenders = []
        for path in apps_dir.rglob("*.py"):
            if "tests" in path.parts or "migrations" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"update_or_create", "get_or_create"}
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "objects"
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id == "AISafetyAlert"
                ):
                    continue
                if "source" not in {kw.arg for kw in node.keywords}:
                    offenders.append(f"{path.relative_to(apps_dir.parent)}:{node.lineno}")
        self.assertGreaterEqual(
            len(list(apps_dir.rglob("*.py"))), 100, "varredura não enxergou o código"
        )
        self.assertEqual(offenders, [], "upsert de AISafetyAlert sem source= no filtro")
