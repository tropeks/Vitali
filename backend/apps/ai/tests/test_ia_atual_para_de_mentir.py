"""
Ordem 025 — a IA atual para de mentir.

Every test here drives the REAL path the system produces (lesson of ordem
021): the DPA is signed through ``DPASigningService`` — which is also what
writes the per-tenant AI ``FeatureFlag`` rows — and the TUSS prompt comes from
``seed_prompt_templates``. Only the network call to Anthropic is replaced.

Defects covered:
  * CID-10 read ``TenantAIConfig.ai_cid10_suggest``, a field that does not
    exist, so it could never run; and it had no consent gate, no PHI scrub and
    no AIUsageLog, so fixing the flag first would have opened a leak.
  * ``PrescriptionSafetyChecker`` read the equally nonexistent
    ``TenantAIConfig.ai_prescription_safety`` — tested in
    ``apps/emr/tests/test_prescription_safety_ordem025.py`` (it needs
    ``apps.pharmacy``, which ``apps.ai`` may not import).
  * The seeded ``tuss_suggest`` prompt asks for ``[{"tuss_code", "rank"}]``
    while the parser expected ``{"suggestions": [{"code"}]}``: every real
    answer fell into the degraded branch.
  * ``run_llm_task``: a Celery LLM wrapper with no consent gate and no caller.
"""

import json
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings

from apps.test_utils import TenantTestCase


def _month_key(schema_name):
    """The Redis key check_monthly_ceiling/increment_monthly_tokens share."""
    from datetime import date

    return f"ai:tokens:{schema_name}:{date.today().strftime('%Y-%m')}"


class _SignedTenantMixin:
    def _sign_dpa_for_real(self):
        from django.contrib.auth import get_user_model

        from apps.core.services.dpa import DPASigningService

        signer = get_user_model().objects.create_user(
            email="signatario.025@clinica.test", password="Signat!025#x", full_name="Signatário"
        )
        DPASigningService(requesting_user=signer).sign(tenant=self.__class__.tenant)


class CID10GateBeforeFlagTest(_SignedTenantMixin, TenantTestCase):
    def setUp(self):
        import datetime

        from apps.core.models import CID10Code
        from apps.emr.models import Patient

        cache.clear()
        CID10Code.objects.using("default").get_or_create(
            code="J18.9", defaults={"description": "Pneumonia não especificada", "active": True}
        )
        self.patient = Patient.objects.create(
            full_name="Mariana Quitéria Soares",
            cpf="529.982.247-25",
            birth_date=datetime.date(1980, 5, 1),
            gender="F",
        )
        self.text = "Mariana Quitéria Soares, CPF 529.982.247-25, com pneumonia há três dias"
        self.llm_answer = json.dumps(
            [{"code": "J18.9", "description": "Pneumonia não especificada", "confidence": 90}]
        )

    def _suggest(self, complete, **kwargs):
        from apps.ai.services_cid10 import CID10Suggester

        with (
            patch(
                "apps.ai.services_cid10._retrieve_candidates",
                return_value=[{"code": "J18.9", "description": "Pneumonia não especificada"}],
            ),
            patch("apps.ai.gateway.ClaudeGateway.complete", complete),
        ):
            return CID10Suggester().suggest(
                text=self.text, schema_name=self.__class__.tenant.schema_name, **kwargs
            )

    @override_settings(FEATURE_AI_CID10=True)
    def test_signed_dpa_reaches_the_llm_scrubbed_and_logged(self):
        from apps.ai.models import AIUsageLog

        self._sign_dpa_for_real()
        before = AIUsageLog.objects.count()
        with patch(
            "apps.ai.gateway.ClaudeGateway.complete", return_value=(self.llm_answer, 50, 20)
        ) as complete:
            result = self._suggest(complete)

        complete.assert_called_once()
        self.assertNotIn("529.982.247-25", complete.call_args.kwargs["user"])
        self.assertEqual([s.code for s in result.suggestions], ["J18.9"])
        self.assertEqual(AIUsageLog.objects.count(), before + 1)
        # The monthly ceiling saw the call (50 in + 20 out).
        self.assertEqual(cache.get(_month_key(self.__class__.tenant.schema_name)), 70)

    @override_settings(FEATURE_AI_CID10=True)
    def test_the_patient_name_is_scrubbed_when_the_encounter_patient_is_known(self):
        """Directed scrub needs the Patient; the view has it via the encounter."""
        self._sign_dpa_for_real()
        with patch(
            "apps.ai.gateway.ClaudeGateway.complete", return_value=(self.llm_answer, 50, 20)
        ) as complete:
            self._suggest(complete, patient=self.patient)

        complete.assert_called_once()
        self.assertNotIn("Mariana Quitéria Soares", complete.call_args.kwargs["user"])

    @override_settings(FEATURE_AI_CID10=True)
    def test_without_dpa_the_llm_is_never_called(self):
        from apps.core.models import FeatureFlag

        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant, module_key="ai_cid10", defaults={"is_enabled": True}
        )
        with patch("apps.ai.gateway.ClaudeGateway.complete") as complete:
            result = self._suggest(complete)
        complete.assert_not_called()
        self.assertEqual(result.suggestions, [])

    def test_signing_the_dpa_alone_does_not_turn_cid10_on(self):
        """FEATURE_AI_CID10 ships OFF: the DPA cascade enables the tenant flag,
        but nothing reaches Anthropic until the global switch is flipped."""
        self._sign_dpa_for_real()
        with patch("apps.ai.gateway.ClaudeGateway.complete") as complete:
            self._suggest(complete)
        complete.assert_not_called()


class TUSSPromptAndParserAgreeTest(TenantTestCase):
    def test_parser_accepts_the_format_the_seeded_prompt_asks_for(self):
        from apps.ai.models import AIPromptTemplate
        from apps.ai.services import _call_llm
        from apps.core.models import TUSSCode

        call_command("seed_prompt_templates", verbosity=0)
        template = AIPromptTemplate.objects.get(name="tuss_suggest", is_active=True)
        # The seeded template itself names the keys the model must return.
        self.assertIn("tuss_code", template.user_prompt_template)

        code = TUSSCode.objects.using("default").create(
            code="40301630",
            description="Hemograma com contagem de plaquetas",
            group="procedimento",
            version="2024-01",
        )
        answer = json.dumps([{"tuss_code": "40301630", "rank": 1}])
        with patch("apps.ai.gateway.ClaudeGateway.complete", return_value=(answer, 30, 10)):
            suggestions, *_ = _call_llm(
                template, "hemograma completo", "sp_sadt", [code], self.__class__.tenant.schema_name
            )
        self.assertEqual([s.tuss_code for s in suggestions], ["40301630"])


class RunLLMTaskIsGoneTest(TenantTestCase):
    def test_ungated_generic_llm_task_no_longer_exists(self):
        import apps.ai.tasks as ai_tasks

        self.assertFalse(hasattr(ai_tasks, "run_llm_task"))
