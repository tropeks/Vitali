"""MB1 — structured microbiology (culture + antibiogram) invariants and API."""

from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.core.models import Role, User
from apps.emr.models import (
    AntibiogramEntry,
    Encounter,
    IsolatedOrganism,
    LabOrder,
    LabOrderItem,
    LabTest,
    MicrobiologyResult,
    Patient,
    Professional,
)
from apps.test_utils import TenantTestCase


class MicrobiologyTestCase(TenantTestCase):
    def setUp(self):
        self.writer_role = Role.objects.create(
            name="micro_writer", permissions=["emr.read", "emr.write"]
        )
        self.reader_role = Role.objects.create(name="micro_reader", permissions=["emr.read"])
        self.writer = User.objects.create_user(
            email="micro-writer@example.com", password="pw", role=self.writer_role
        )
        self.reader = User.objects.create_user(
            email="micro-reader@example.com", password="pw", role=self.reader_role
        )
        self.professional = Professional.objects.create(
            user=self.writer,
            council_type="CRM",
            council_number="MB-1",
            council_state="SP",
        )
        self.patient = Patient.objects.create(
            full_name="Paciente Micro",
            birth_date="1990-01-01",
            gender="F",
            cpf="51111111111",
        )
        self.encounter = Encounter.objects.create(
            patient=self.patient, professional=self.professional
        )
        self.test = LabTest.objects.create(
            code="UROC",
            name="Urocultura",
            category=LabTest.Category.MICROBIOLOGY,
            result_type=LabTest.ResultType.MICROBIOLOGY,
        )
        self.order = LabOrder.objects.create(
            patient=self.patient, encounter=self.encounter, requested_by=self.writer
        )
        self.item = LabOrderItem.objects.create(
            order=self.order,
            test=self.test,
            test_name=self.test.name,
            category=LabTest.Category.MICROBIOLOGY,
            result_type=LabTest.ResultType.MICROBIOLOGY,
            specimen_type="Urina",
        )

    def client_for(self, user):
        client = APIClient()
        client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        client.force_authenticate(user=user)
        return client

    # ── Model invariants ────────────────────────────────────────────────
    def test_one_result_per_order_item(self):
        MicrobiologyResult.objects.create(
            order_item=self.item, culture_result=MicrobiologyResult.CultureResult.POSITIVA
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            MicrobiologyResult.objects.create(order_item=self.item)

    def test_positive_culture_with_organism_and_antibiogram(self):
        result = MicrobiologyResult.objects.create(
            order_item=self.item,
            culture_result=MicrobiologyResult.CultureResult.POSITIVA,
            specimen="urocultura",
            gram_stain="Bacilos Gram-negativos",
        )
        organism = IsolatedOrganism.objects.create(
            result=result,
            organism_name="Escherichia coli",
            colony_count=">100.000 UFC/mL",
        )
        AntibiogramEntry.objects.create(
            organism=organism,
            antibiotic="Ciprofloxacino",
            interpretation=AntibiogramEntry.Interpretation.SENSIVEL,
        )
        AntibiogramEntry.objects.create(
            organism=organism,
            antibiotic="Gentamicina",
            interpretation=AntibiogramEntry.Interpretation.INTERMEDIARIO,
        )
        AntibiogramEntry.objects.create(
            organism=organism,
            antibiotic="Ampicilina",
            interpretation=AntibiogramEntry.Interpretation.RESISTENTE,
        )
        self.assertEqual(self.item.microbiology_result, result)
        self.assertEqual(result.organisms.count(), 1)
        self.assertEqual(organism.antibiogram.count(), 3)

    def test_unique_organism_antibiotic(self):
        result = MicrobiologyResult.objects.create(order_item=self.item)
        organism = IsolatedOrganism.objects.create(
            result=result, organism_name="Klebsiella pneumoniae"
        )
        AntibiogramEntry.objects.create(
            organism=organism,
            antibiotic="Meropenem",
            interpretation=AntibiogramEntry.Interpretation.SENSIVEL,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            AntibiogramEntry.objects.create(
                organism=organism,
                antibiotic="Meropenem",
                interpretation=AntibiogramEntry.Interpretation.RESISTENTE,
            )

    def test_resistance_surveillance_query(self):
        result = MicrobiologyResult.objects.create(
            order_item=self.item, culture_result=MicrobiologyResult.CultureResult.POSITIVA
        )
        resistant = IsolatedOrganism.objects.create(result=result, organism_name="E. coli")
        sensitive = IsolatedOrganism.objects.create(
            result=result, organism_name="Proteus mirabilis"
        )
        AntibiogramEntry.objects.create(
            organism=resistant,
            antibiotic="Ampicilina",
            interpretation=AntibiogramEntry.Interpretation.RESISTENTE,
        )
        AntibiogramEntry.objects.create(
            organism=sensitive,
            antibiotic="Ampicilina",
            interpretation=AntibiogramEntry.Interpretation.SENSIVEL,
        )
        resistant_isolates = IsolatedOrganism.objects.filter(
            antibiogram__antibiotic="Ampicilina",
            antibiogram__interpretation=AntibiogramEntry.Interpretation.RESISTENTE,
        )
        self.assertEqual(list(resistant_isolates), [resistant])

    # ── API contract + RBAC ────────────────────────────────────────────
    def test_viewset_create_list_retrieve(self):
        client = self.client_for(self.writer)
        create = client.post(
            "/api/v1/microbiology-results/",
            {
                "order_item": str(self.item.id),
                "culture_result": "positiva",
                "specimen": "hemocultura",
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201, create.content)
        result_id = create.data["id"]
        self.assertEqual(create.data["created_by"], self.writer.id)

        org = client.post(
            "/api/v1/isolated-organisms/",
            {"result": result_id, "organism_name": "Staphylococcus aureus"},
            format="json",
        )
        self.assertEqual(org.status_code, 201, org.content)
        organism_id = org.data["id"]

        abg = client.post(
            "/api/v1/antibiogram-entries/",
            {"organism": organism_id, "antibiotic": "Oxacilina", "interpretation": "R"},
            format="json",
        )
        self.assertEqual(abg.status_code, 201, abg.content)

        listing = client.get("/api/v1/microbiology-results/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data["results"]), 1)

        retrieve = client.get(f"/api/v1/microbiology-results/{result_id}/")
        self.assertEqual(retrieve.status_code, 200)
        self.assertEqual(retrieve.data["organisms"][0]["antibiogram"][0]["antibiotic"], "Oxacilina")

    def test_surveillance_filter_endpoint(self):
        result = MicrobiologyResult.objects.create(order_item=self.item)
        organism = IsolatedOrganism.objects.create(result=result, organism_name="E. coli")
        AntibiogramEntry.objects.create(
            organism=organism,
            antibiotic="Ampicilina",
            interpretation=AntibiogramEntry.Interpretation.RESISTENTE,
        )
        AntibiogramEntry.objects.create(
            organism=organism,
            antibiotic="Amicacina",
            interpretation=AntibiogramEntry.Interpretation.SENSIVEL,
        )
        resp = self.client_for(self.reader).get(
            "/api/v1/antibiogram-entries/?antibiotic=Ampicilina&interpretation=R"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["antibiotic"], "Ampicilina")

    def test_reader_cannot_write(self):
        resp = self.client_for(self.reader).post(
            "/api/v1/microbiology-results/",
            {"order_item": str(self.item.id), "culture_result": "positiva"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_reader_can_read(self):
        MicrobiologyResult.objects.create(order_item=self.item)
        resp = self.client_for(self.reader).get("/api/v1/microbiology-results/")
        self.assertEqual(resp.status_code, 200)

    def test_create_result_with_organisms_and_antibiogram_nested(self):
        # LAB-3a: post the whole tree (culture + organisms + antibiogram) in one POST.
        payload = {
            "order_item": str(self.item.id),
            "culture_result": "positiva",
            "specimen": "urocultura",
            "organisms_input": [
                {
                    "organism_name": "Escherichia coli",
                    "colony_count": ">100.000 UFC/mL",
                    "antibiogram": [
                        {"antibiotic": "Ciprofloxacino", "interpretation": "S"},
                        {"antibiotic": "Ampicilina", "interpretation": "R"},
                    ],
                }
            ],
        }
        resp = self.client_for(self.writer).post(
            "/api/v1/microbiology-results/", payload, format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        result = MicrobiologyResult.objects.get(pk=resp.data["id"])
        self.assertEqual(result.culture_result, "positiva")
        self.assertEqual(result.created_by_id, self.writer.id)
        organism = result.organisms.get()
        self.assertEqual(organism.organism_name, "Escherichia coli")
        self.assertEqual(organism.antibiogram.count(), 2)
        self.assertEqual(
            set(organism.antibiogram.values_list("interpretation", flat=True)), {"S", "R"}
        )
        # nested tree also read back on the result serializer (order-independent)
        abx_names = {a["antibiotic"] for a in resp.data["organisms"][0]["antibiogram"]}
        self.assertEqual(abx_names, {"Ciprofloxacino", "Ampicilina"})

    def test_reader_cannot_create_nested(self):
        resp = self.client_for(self.reader).post(
            "/api/v1/microbiology-results/",
            {"order_item": str(self.item.id), "organisms_input": []},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_patient_filter_endpoint(self):
        # Result for our patient (via self.item → self.order → self.patient).
        MicrobiologyResult.objects.create(
            order_item=self.item, culture_result=MicrobiologyResult.CultureResult.POSITIVA
        )
        # A second patient with their own order/item/result must NOT leak in.
        other_patient = Patient.objects.create(
            full_name="Outro Paciente", birth_date="1985-05-05", gender="M", cpf="52998224725"
        )
        other_order = LabOrder.objects.create(
            patient=other_patient, encounter=self.encounter, requested_by=self.writer
        )
        other_item = LabOrderItem.objects.create(
            order=other_order,
            test=self.test,
            test_name=self.test.name,
            category=LabTest.Category.MICROBIOLOGY,
            result_type=LabTest.ResultType.MICROBIOLOGY,
        )
        MicrobiologyResult.objects.create(order_item=other_item)

        resp = self.client_for(self.reader).get(
            f"/api/v1/microbiology-results/?patient={self.patient.id}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["culture_result"], "positiva")
