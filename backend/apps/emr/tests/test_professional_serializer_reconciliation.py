"""
A1-T4 — ProfessionalSerializer exposes the read-only reconciliation flags.

``cbo_unmatched`` / ``cnes_unmatched`` tell the UI whether a professional's raw
CBO/CNES code reconciled to the governed SHARED catalog. They must serialize and
must be read-only (set by the model's cbo_code/cnes_code setters, never by the
client).
"""

from django.contrib.auth import get_user_model

from apps.core.cbo_cnes_models import CBOCode
from apps.emr.models import Professional
from apps.emr.serializers import ProfessionalSerializer
from apps.test_utils import TenantTestCase


class ProfessionalReconciliationFlagsTests(TenantTestCase):
    def _make(self, **kwargs) -> Professional:
        User = get_user_model()
        user = User.objects.create_user(
            email=kwargs.pop("email", "prof.recon@test.com"),
            password="TestPass123!",
            full_name="Prof Recon",
        )
        return Professional.objects.create(
            user=user,
            council_type="CRM",
            council_number="90001",
            council_state="SP",
            specialty="Clínica",
            **kwargs,
        )

    def test_flags_present_in_serialized_output(self):
        prof = self._make()
        data = ProfessionalSerializer(prof).data
        self.assertIn("cbo_unmatched", data)
        self.assertIn("cnes_unmatched", data)

    def test_matched_cbo_serializes_false(self):
        CBOCode.objects.create(code="225125", display="Médico clínico", family="2251")
        prof = self._make(email="prof.matched@test.com")
        prof.cbo_code = "225125"  # setter reconciles → cbo_unmatched=False
        prof.save()
        data = ProfessionalSerializer(prof).data
        self.assertFalse(data["cbo_unmatched"])

    def test_unmatched_cbo_serializes_true(self):
        prof = self._make(email="prof.unmatched@test.com")
        prof.cbo_code = "000000"  # no governed CBOCode → cbo_unmatched=True
        prof.save()
        data = ProfessionalSerializer(prof).data
        self.assertTrue(data["cbo_unmatched"])

    def test_flags_are_read_only(self):
        fields = ProfessionalSerializer().fields
        self.assertTrue(fields["cbo_unmatched"].read_only)
        self.assertTrue(fields["cnes_unmatched"].read_only)
