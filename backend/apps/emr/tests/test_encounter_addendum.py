"""
Sprint E6-T1 — EncounterAddendum model.

CFM requirement: a signed clinical document is IMMUTABLE. Corrections happen
via an APPENDED addendum that references the original, never by editing it.

Covers:
- addending an unsigned document is rejected (Encounter and ClinicalDocument)
- addending a signed document succeeds and does not mutate the original
- multiple addenda form an ordered chain (sequence + previous_addendum)
- an addendum cannot be edited once created (append-only)
- an addendum cannot be deleted once created (append-only)
- creating an addendum for a non-existent document is rejected
"""

from django.utils import timezone

from apps.core.models import Role, User
from apps.core.permissions import DEFAULT_ROLES
from apps.emr.models import ClinicalDocument, Encounter, EncounterAddendum, Patient, Professional
from apps.test_utils import TenantTestCase


def _make_infra():
    role_md = Role.objects.create(name="medico_addendum", permissions=DEFAULT_ROLES["medico"])
    doctor = User.objects.create_user(email="addendum_doc@t.com", password="pw", role=role_md)
    author = User.objects.create_user(email="addendum_author@t.com", password="pw", role=role_md)
    patient = Patient.objects.create(
        full_name="Adendo Patient", birth_date="1980-03-20", gender="M", cpf="55566677788"
    )
    prof = Professional.objects.create(
        user=doctor, council_type="CRM", council_number="1010", council_state="SP"
    )
    return doctor, author, patient, prof


def _make_encounter(patient, prof, signed=False):
    encounter = Encounter.objects.create(
        patient=patient, professional=prof, chief_complaint="Dor abdominal"
    )
    if signed:
        encounter.status = "signed"
        encounter.signed_at = timezone.now()
        encounter.signed_by = prof.user
        encounter.signature_hash = "deadbeef"
        encounter.save(update_fields=["status", "signed_at", "signed_by", "signature_hash"])
    return encounter


def _make_document(encounter, signed=False):
    doc = ClinicalDocument.objects.create(
        encounter=encounter, doc_type="certificate", content="Atesto que o paciente..."
    )
    if signed:
        doc.sign(encounter.professional.user, is_icp_brasil=False, signature_hash="cafebabe")
    return doc


class TestEncounterAddendumRejectsUnsigned(TenantTestCase):
    def setUp(self):
        self.doctor, self.author, self.patient, self.prof = _make_infra()

    def test_addend_unsigned_encounter_rejected(self):
        encounter = _make_encounter(self.patient, self.prof, signed=False)
        with self.assertRaises(ValueError) as ctx:
            EncounterAddendum.objects.create_addendum(
                target=encounter,
                author=self.author,
                reason="Correção",
                body="Complemento clínico",
            )
        self.assertIn("assinado", str(ctx.exception))
        self.assertEqual(EncounterAddendum.objects.count(), 0)

    def test_addend_unsigned_clinical_document_rejected(self):
        encounter = _make_encounter(self.patient, self.prof, signed=False)
        doc = _make_document(encounter, signed=False)
        with self.assertRaises(ValueError):
            EncounterAddendum.objects.create_addendum(
                target=doc,
                author=self.author,
                reason="Correção",
                body="Complemento clínico",
            )
        self.assertEqual(EncounterAddendum.objects.count(), 0)

    def test_addend_nonexistent_target_rejected(self):
        import uuid

        ghost = Encounter(id=uuid.uuid4())
        with self.assertRaises(ValueError):
            EncounterAddendum.objects.create_addendum(
                target=ghost,
                author=self.author,
                reason="Correção",
                body="Complemento",
            )


class TestEncounterAddendumOnSignedEncounter(TenantTestCase):
    def setUp(self):
        self.doctor, self.author, self.patient, self.prof = _make_infra()
        self.encounter = _make_encounter(self.patient, self.prof, signed=True)

    def test_addend_signed_encounter_succeeds(self):
        addendum = EncounterAddendum.objects.create_addendum(
            target=self.encounter,
            author=self.author,
            reason="Erro de digitação no CID",
            body="CID correto: J45.0",
        )
        self.assertEqual(addendum.sequence, 1)
        self.assertIsNone(addendum.previous_addendum)
        self.assertEqual(addendum.target_type, EncounterAddendum.TARGET_ENCOUNTER)
        self.assertEqual(addendum.target_id, str(self.encounter.id))
        self.assertEqual(addendum.reason, "Erro de digitação no CID")
        self.assertEqual(addendum.body, "CID correto: J45.0")
        self.assertEqual(addendum.author, self.author)

    def test_original_content_byte_identical_after_addendum(self):
        original_complaint = self.encounter.chief_complaint
        original_hash = self.encounter.signature_hash
        original_signed_at = self.encounter.signed_at

        EncounterAddendum.objects.create_addendum(
            target=self.encounter,
            author=self.author,
            reason="Complemento",
            body="Informação adicional",
        )

        self.encounter.refresh_from_db()
        self.assertEqual(self.encounter.chief_complaint, original_complaint)
        self.assertEqual(self.encounter.signature_hash, original_hash)
        self.assertEqual(self.encounter.signed_at, original_signed_at)
        self.assertEqual(self.encounter.status, "signed")

    def test_multiple_addenda_form_ordered_chain(self):
        a1 = EncounterAddendum.objects.create_addendum(
            target=self.encounter, author=self.author, reason="r1", body="b1"
        )
        a2 = EncounterAddendum.objects.create_addendum(
            target=self.encounter, author=self.author, reason="r2", body="b2"
        )
        a3 = EncounterAddendum.objects.create_addendum(
            target=self.encounter, author=self.author, reason="r3", body="b3"
        )

        self.assertEqual(a1.sequence, 1)
        self.assertEqual(a2.sequence, 2)
        self.assertEqual(a3.sequence, 3)
        self.assertIsNone(a1.previous_addendum)
        self.assertEqual(a2.previous_addendum_id, a1.id)
        self.assertEqual(a3.previous_addendum_id, a2.id)

        chain = list(EncounterAddendum.objects.for_target(self.encounter))
        self.assertEqual([a.id for a in chain], [a1.id, a2.id, a3.id])

    def test_addendum_cannot_be_edited(self):
        addendum = EncounterAddendum.objects.create_addendum(
            target=self.encounter, author=self.author, reason="r1", body="b1"
        )
        addendum.body = "tampered"
        with self.assertRaises(ValueError):
            addendum.save()

    def test_addendum_cannot_be_deleted(self):
        addendum = EncounterAddendum.objects.create_addendum(
            target=self.encounter, author=self.author, reason="r1", body="b1"
        )
        with self.assertRaises(ValueError):
            addendum.delete()
        self.assertTrue(EncounterAddendum.objects.filter(id=addendum.id).exists())

    def test_optional_own_signature_can_be_set_at_creation(self):
        now = timezone.now()
        addendum = EncounterAddendum.objects.create_addendum(
            target=self.encounter,
            author=self.author,
            reason="r1",
            body="b1",
            signed_at=now,
            signed_by=self.author,
            signature_hash="addendumhash",
        )
        self.assertTrue(addendum.is_signed)
        self.assertEqual(addendum.signed_by, self.author)
        self.assertEqual(addendum.signature_hash, "addendumhash")


class TestEncounterAddendumOnSignedClinicalDocument(TenantTestCase):
    def setUp(self):
        self.doctor, self.author, self.patient, self.prof = _make_infra()
        self.encounter = _make_encounter(self.patient, self.prof, signed=False)
        self.doc = _make_document(self.encounter, signed=True)

    def test_addend_signed_document_succeeds(self):
        addendum = EncounterAddendum.objects.create_addendum(
            target=self.doc,
            author=self.author,
            reason="Ajuste de posologia",
            body="Dose correta: 500mg 8/8h",
        )
        self.assertEqual(addendum.sequence, 1)
        self.assertEqual(addendum.target_type, EncounterAddendum.TARGET_CLINICAL_DOCUMENT)
        self.assertEqual(addendum.target_id, str(self.doc.id))

    def test_original_document_content_byte_identical_after_addendum(self):
        original_content = self.doc.content
        original_hash = self.doc.signature_hash

        EncounterAddendum.objects.create_addendum(
            target=self.doc, author=self.author, reason="r", body="b"
        )

        self.doc.refresh_from_db()
        self.assertEqual(self.doc.content, original_content)
        self.assertEqual(self.doc.signature_hash, original_hash)

    def test_separate_chains_per_target_do_not_interfere(self):
        """Two different signed documents each start their own chain at sequence 1."""
        encounter2 = _make_encounter(self.patient, self.prof, signed=True)

        a_doc = EncounterAddendum.objects.create_addendum(
            target=self.doc, author=self.author, reason="r", body="b"
        )
        a_enc = EncounterAddendum.objects.create_addendum(
            target=encounter2, author=self.author, reason="r", body="b"
        )

        self.assertEqual(a_doc.sequence, 1)
        self.assertEqual(a_enc.sequence, 1)
        self.assertNotEqual(a_doc.target_type, a_enc.target_type)
