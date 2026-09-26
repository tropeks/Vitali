"""
Ordem 028 (revisão, P1) — o Django admin não pode validar uma DoseRule.

``DoseRuleAdmin`` não restringia nenhum campo de validação: a tela
``/admin/pharmacy/doserule/<id>/change/`` deixava marcar
``status_validacao=validado`` e digitar o retrato do CRF à mão, contornando
inteiramente o CRF ativo que ``DoseRuleViewSet.validate`` exige (ordem 028).

Este teste prova, pelo caminho mais barato (``ModelAdmin.get_form``), que
nenhum dos campos de validação/procedência aparece editável no form do admin.
"""

from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.pharmacy.admin import DoseRuleAdmin, DoseRuleInline, MedicationFormularyAdmin
from apps.pharmacy.models import DoseRule, Drug, MedicationFormulary
from apps.test_utils import TenantTestCase

# Ordem 028: campos que só a action DoseRuleViewSet.validate (CRF ativo
# obrigatório) pode gravar. Nenhum deles pode ser um campo editável do admin.
_VALIDATION_FIELDS = frozenset(
    {
        "status_validacao",
        "validated_by",
        "validated_at",
        "validado_crf_numero",
        "validado_crf_uf",
    }
)
# Procedência: também nunca deve ser reescrita à mão por fora do importador.
_PROVENANCE_FIELDS = frozenset({"fonte_tipo", "fonte_ref", "fonte_trecho"})


class DoseRuleAdminLocksValidationFieldsTest(TenantTestCase):
    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_user(
            email="admin.028@clinica.test",
            password="Admin!028#x",
            is_staff=True,
            is_superuser=True,
        )
        drug = Drug.objects.create(name="FAKE-AdminLock", generic_name="fake_adminlock")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("10.000"),
            strength_unit="mg",
            route="IV",
            active=True,
        )
        self.rule = DoseRule.objects.create(
            formulary=formulary,
            basis="fixed",
            dose_unit="mg",
            min_per_dose=Decimal("1.0000"),
            max_per_dose=Decimal("2.0000"),
            absolute_max_dose=Decimal("2.0000"),
            active=True,
            validated=False,
        )

    def _change_request(self, path):
        request = RequestFactory().get(path)
        request.user = self.superuser
        return request

    def test_doserule_admin_form_does_not_expose_validation_or_provenance_fields(self):
        model_admin = DoseRuleAdmin(DoseRule, admin.site)
        request = self._change_request(f"/admin/pharmacy/doserule/{self.rule.id}/change/")
        form_class = model_admin.get_form(request, obj=self.rule)

        editable = set(form_class.base_fields)
        leaked_validation = editable & _VALIDATION_FIELDS
        leaked_provenance = editable & _PROVENANCE_FIELDS

        self.assertEqual(
            leaked_validation,
            set(),
            f"campos de validação editáveis no admin: {leaked_validation}",
        )
        self.assertEqual(
            leaked_provenance,
            set(),
            f"campos de procedência editáveis no admin: {leaked_provenance}",
        )

    def test_doserule_admin_readonly_fields_name_every_validation_field(self):
        """Belt-and-suspenders: `readonly_fields` itself must name every one of
        these fields — not just "the form happens to not show them today"."""
        model_admin = DoseRuleAdmin(DoseRule, admin.site)
        request = self._change_request(f"/admin/pharmacy/doserule/{self.rule.id}/change/")
        readonly = set(model_admin.get_readonly_fields(request, obj=self.rule))

        missing = (_VALIDATION_FIELDS | _PROVENANCE_FIELDS) - readonly
        self.assertEqual(missing, set(), f"faltando em readonly_fields: {missing}")

    def test_doserule_inline_does_not_expose_validation_or_provenance_fields(self):
        inline_fields = set(DoseRuleInline.fields)
        leaked = inline_fields & (_VALIDATION_FIELDS | _PROVENANCE_FIELDS)
        self.assertEqual(leaked, set(), f"DoseRuleInline expõe: {leaked}")

    def test_medicationformulary_admin_does_not_expose_doserule_validation_fields(self):
        """MedicationFormularyAdmin has no own validation fields, but its
        inline (DoseRuleInline) is checked above; this just confirms its own
        change form carries nothing extra."""
        drug = Drug.objects.create(name="FAKE-AdminLock-MF", generic_name="fake_adminlock_mf")
        formulary = MedicationFormulary.objects.create(
            drug=drug,
            strength_value=Decimal("5.000"),
            strength_unit="mg",
            route="PO",
            active=True,
        )
        model_admin = MedicationFormularyAdmin(MedicationFormulary, admin.site)
        request = self._change_request(
            f"/admin/pharmacy/medicationformulary/{formulary.id}/change/"
        )
        form_class = model_admin.get_form(request, obj=formulary)
        editable = set(form_class.base_fields)
        leaked = editable & (_VALIDATION_FIELDS | _PROVENANCE_FIELDS)
        self.assertEqual(leaked, set())
