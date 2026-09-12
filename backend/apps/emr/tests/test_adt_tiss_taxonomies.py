"""
Onda 4, Fatia 3 — taxonomias TISS 4.01.00 de internação em ``emr.Admission``.

``carater_atendimento``/``tipo_internacao``/``regime_internacao`` (capturados na
admissão) e ``disposition_ans_code`` (capturado na alta, campo irmão de
``disposition`` — NÃO o substitui). Todos opcionais: internação existente sem os
campos continua válida, e valor fora do enum fechado é rejeitado tanto no model
(``full_clean``) quanto na API (``ChoiceField``/serializer).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.test import APIClient

from apps.core.models import BedType, Role, User
from apps.emr.models import Admission, Bed, InpatientUnit, Patient, Professional, Room
from apps.emr.services import adt as adt_service
from apps.organization.models import Facility, LegalEntity
from apps.test_utils import TenantTestCase

BASE = "/api/v1"

ADMIT_PERMS = ["adt.admit", "adt.discharge", "beds.read"]


class TissTaxonomyTestBase(TenantTestCase):
    def setUp(self):
        self.role = Role.objects.create(name="recepcao_interna", permissions=ADMIT_PERMS)
        self.user = User.objects.create_user(email="adm@t.com", password="pw", role=self.role)
        self.prof = Professional.objects.create(
            user=self.user, council_type="CRM", council_number="12345", council_state="SP"
        )
        self.legal = LegalEntity.objects.create(code="LE1", name="Hospital SA")
        self.facility = Facility.objects.create(
            code="FAC1", name="Hospital Central", legal_entity=self.legal
        )
        self.bed_type = BedType.objects.create(
            code="74", display="UTI adulto tipo II", category="Complementar"
        )
        self.unit = InpatientUnit.objects.create(facility=self.facility, name="Ala A", code="ALA-A")
        self.room = Room.objects.create(unit=self.unit, name="101")
        self.bed = Bed.objects.create(
            room=self.room, unit=self.unit, identifier="101-A", bed_type=self.bed_type
        )
        self.patient = Patient.objects.create(
            full_name="João Internado", birth_date="1980-01-01", gender="M", cpf="52998224725"
        )

    def _client(self):
        c = APIClient()
        c.defaults["SERVER_NAME"] = self.__class__.domain.domain
        c.force_authenticate(self.user)
        return c


class TestModelDefaultsAndValidation(TissTaxonomyTestBase):
    def test_existing_admission_without_tiss_fields_stays_valid(self):
        """Internação criada sem passar os campos novos (fluxo pré-Fatia-3)
        continua válida: default '' + blank=True, sem exigir backfill."""
        admission = adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.user,
        )
        admission.full_clean()
        assert admission.carater_atendimento == ""
        assert admission.tipo_internacao == ""
        assert admission.regime_internacao == ""
        assert admission.disposition_ans_code == ""

    def test_admit_sets_tiss_taxonomies(self):
        admission = adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            carater_atendimento=Admission.CaraterAtendimento.ELETIVO,
            tipo_internacao=Admission.TipoInternacao.CIRURGICO,
            regime_internacao=Admission.RegimeInternacao.HOSPITALAR,
            actor=self.user,
        )
        admission.refresh_from_db()
        assert admission.carater_atendimento == "1"
        assert admission.tipo_internacao == "2"
        assert admission.regime_internacao == "1"

    def test_discharge_sets_disposition_ans_code_without_touching_disposition(self):
        admission = adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.user,
        )
        discharged = adt_service.discharge(
            admission=admission,
            disposition="alta_melhorada",
            disposition_ans_code=Admission.MotivoEncerramento.ALTA_MELHORADO,
            actor=self.user,
        )
        assert discharged.disposition == "alta_melhorada"
        assert discharged.disposition_ans_code == "11"

    def test_invalid_carater_atendimento_rejected_by_full_clean(self):
        admission = adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.user,
        )
        admission.carater_atendimento = "9"  # não está em dm_caraterAtendimento
        try:
            admission.full_clean()
            raise AssertionError("expected invalid caráter de atendimento to raise")
        except DjangoValidationError as exc:
            assert "carater_atendimento" in exc.message_dict

    def test_invalid_disposition_ans_code_rejected_by_full_clean(self):
        admission = adt_service.admit(
            patient=self.patient,
            bed=self.bed,
            admitting_professional=self.prof,
            attending_professional=self.prof,
            admission_source="emergencia",
            actor=self.user,
        )
        admission.disposition_ans_code = "99"  # não está em dm_motivoSaida
        try:
            admission.full_clean()
            raise AssertionError("expected invalid motivo de encerramento to raise")
        except DjangoValidationError as exc:
            assert "disposition_ans_code" in exc.message_dict


class TestAdmissionAPI(TissTaxonomyTestBase):
    def _admit_payload(self, **kw):
        payload = {
            "patient": str(self.patient.id),
            "bed": str(self.bed.id),
            "admitting_professional": str(self.prof.id),
            "attending_professional": str(self.prof.id),
            "admission_source": "emergencia",
        }
        payload.update(kw)
        return payload

    def test_api_accepts_and_returns_tiss_fields_on_admit(self):
        resp = self._client().post(
            f"{BASE}/admissions/",
            self._admit_payload(
                carater_atendimento="1",
                tipo_internacao="2",
                regime_internacao="1",
            ),
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.data["carater_atendimento"] == "1"
        assert resp.data["tipo_internacao"] == "2"
        assert resp.data["regime_internacao"] == "1"
        admission = Admission.objects.get(pk=resp.data["id"])
        assert admission.carater_atendimento == "1"

    def test_api_rejects_invalid_tiss_taxonomy_value(self):
        resp = self._client().post(
            f"{BASE}/admissions/",
            self._admit_payload(tipo_internacao="9"),
            format="json",
        )
        assert resp.status_code == 400, resp.content
        assert "tipo_internacao" in resp.data

    def test_api_accepts_and_returns_disposition_ans_code_on_discharge(self):
        create = self._client().post(f"{BASE}/admissions/", self._admit_payload(), format="json")
        admission_id = create.data["id"]
        resp = self._client().post(
            f"{BASE}/admissions/{admission_id}/discharge/",
            {"disposition": "alta_melhorada", "disposition_ans_code": "11"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["disposition"] == "alta_melhorada"
        assert resp.data["disposition_ans_code"] == "11"

    def test_api_rejects_invalid_disposition_ans_code(self):
        create = self._client().post(f"{BASE}/admissions/", self._admit_payload(), format="json")
        admission_id = create.data["id"]
        resp = self._client().post(
            f"{BASE}/admissions/{admission_id}/discharge/",
            {"disposition": "alta_melhorada", "disposition_ans_code": "99"},
            format="json",
        )
        assert resp.status_code == 400, resp.content
        assert "disposition_ans_code" in resp.data

    def test_discharge_without_disposition_ans_code_still_works(self):
        """Regressão: internação sem preencher o código TISS na alta continua
        dando alta normalmente — o campo é opcional."""
        create = self._client().post(f"{BASE}/admissions/", self._admit_payload(), format="json")
        admission_id = create.data["id"]
        resp = self._client().post(
            f"{BASE}/admissions/{admission_id}/discharge/",
            {"disposition": "alta_melhorada"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.data["disposition_ans_code"] == ""
