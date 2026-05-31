"""
Offline tests for the Orthanc → Vitali ingestion (E-012).

No network: a `FakeOrthancClient` stands in for `OrthancClient`, returning
canned `/changes` pages and `/studies/{id}` payloads. Covers UID match,
accession fallback, no-match skip, multi-tenant isolation, idempotency, and the
ORTHANC_URL-empty no-op of the Celery task.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django_tenants.utils import get_public_schema_name, schema_context

from apps.core.models import Tenant
from apps.emr.models import Patient
from apps.imaging.models import DicomStudy
from apps.imaging.services import orthanc_sync
from apps.imaging.services.orthanc_client import OrthancClient
from apps.test_utils import TenantTestCase

UID_CT = "1.2.840.113619.2.55.3.604688119.1234567890.001"
ACC_CT = "ACC-2026-001"


def _study_payload(uid, accession, n_series=3, n_instances=240):
    return {
        "study": {
            "MainDicomTags": {"StudyInstanceUID": uid, "AccessionNumber": accession},
            "Series": ["s"] * n_series,
        },
        "statistics": {"CountSeries": n_series, "CountInstances": n_instances},
    }


class FakeOrthancClient(OrthancClient):
    """In-memory stand-in: serves canned changes pages + study payloads."""

    def __init__(self, *, changes, studies):
        # Deliberately skip super().__init__ — no settings/network needed.
        self._changes = changes  # list of pages: {"Changes":[...],"Last":int,"Done":bool}
        self._studies = studies  # {orthanc_id: {"study":..., "statistics":...}}
        self.get_changes_calls = 0

    def get_changes(self, since, limit=100):
        self.get_changes_calls += 1
        # Serve only the page(s) whose changes are strictly after `since`.
        for page in self._changes:
            relevant = [c for c in page["Changes"] if c["Seq"] > since]
            if relevant or page["Last"] > since:
                return {"Changes": relevant, "Last": page["Last"], "Done": page["Done"]}
        return {"Changes": [], "Last": since, "Done": True}

    def get_study(self, orthanc_id):
        return self._studies[orthanc_id]["study"]

    def get_study_statistics(self, orthanc_id):
        return self._studies[orthanc_id]["statistics"]


class OrthancSyncTest(TenantTestCase):
    def setUp(self):
        cache.delete(orthanc_sync.CURSOR_CACHE_KEY)
        self.patient = Patient.objects.create(
            full_name="Ana Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
        )
        self.ct_study = DicomStudy.objects.create(
            patient=self.patient,
            study_instance_uid=UID_CT,
            accession_number=ACC_CT,
            modality="CT",
            study_date=datetime(2026, 5, 18, 14, 30, tzinfo=UTC),
        )

    def tearDown(self):
        cache.delete(orthanc_sync.CURSOR_CACHE_KEY)

    def _client(self, changes, studies):
        return FakeOrthancClient(changes=changes, studies=studies)

    def test_match_by_study_instance_uid(self):
        client = self._client(
            changes=[
                {
                    "Changes": [{"Seq": 1, "ChangeType": "StableStudy", "ID": "orth-1"}],
                    "Last": 1,
                    "Done": True,
                }
            ],
            studies={"orth-1": _study_payload(UID_CT, "", n_series=4, n_instances=120)},
        )
        summary = orthanc_sync.sync_orthanc_studies(client=client)

        self.assertEqual(summary, {"scanned": 1, "matched": 1, "skipped": 0})
        self.ct_study.refresh_from_db()
        self.assertEqual(self.ct_study.orthanc_study_id, "orth-1")
        self.assertEqual(self.ct_study.number_of_series, 4)
        self.assertEqual(self.ct_study.number_of_instances, 120)
        self.assertEqual(cache.get(orthanc_sync.CURSOR_CACHE_KEY), 1)

    def test_match_by_accession_when_uid_differs(self):
        client = self._client(
            changes=[
                {
                    "Changes": [{"Seq": 5, "ChangeType": "StableStudy", "ID": "orth-acc"}],
                    "Last": 5,
                    "Done": True,
                }
            ],
            # UID does not match our row; AccessionNumber does.
            studies={"orth-acc": _study_payload("9.9.9.UNKNOWN.UID", ACC_CT)},
        )
        summary = orthanc_sync.sync_orthanc_studies(client=client)

        self.assertEqual(summary["matched"], 1)
        self.ct_study.refresh_from_db()
        self.assertEqual(self.ct_study.orthanc_study_id, "orth-acc")

    def test_no_match_is_skipped_and_creates_nothing(self):
        before = DicomStudy.objects.count()
        client = self._client(
            changes=[
                {
                    "Changes": [{"Seq": 2, "ChangeType": "StableStudy", "ID": "orth-x"}],
                    "Last": 2,
                    "Done": True,
                }
            ],
            studies={"orth-x": _study_payload("totally.unknown.uid", "NO-SUCH-ACC")},
        )
        summary = orthanc_sync.sync_orthanc_studies(client=client)

        self.assertEqual(summary, {"scanned": 1, "matched": 0, "skipped": 1})
        self.assertEqual(DicomStudy.objects.count(), before)
        self.ct_study.refresh_from_db()
        self.assertEqual(self.ct_study.orthanc_study_id, "")
        # Cursor still advances past the processed change.
        self.assertEqual(cache.get(orthanc_sync.CURSOR_CACHE_KEY), 2)

    def test_non_stable_study_changes_ignored(self):
        client = self._client(
            changes=[
                {
                    "Changes": [
                        {"Seq": 1, "ChangeType": "NewInstance", "ID": "orth-1"},
                        {"Seq": 2, "ChangeType": "StableSeries", "ID": "orth-1"},
                    ],
                    "Last": 2,
                    "Done": True,
                }
            ],
            studies={"orth-1": _study_payload(UID_CT, "")},
        )
        summary = orthanc_sync.sync_orthanc_studies(client=client)
        self.assertEqual(summary, {"scanned": 0, "matched": 0, "skipped": 0})
        self.ct_study.refresh_from_db()
        self.assertEqual(self.ct_study.orthanc_study_id, "")

    def test_idempotent_second_run_does_nothing_new(self):
        client = self._client(
            changes=[
                {
                    "Changes": [{"Seq": 1, "ChangeType": "StableStudy", "ID": "orth-1"}],
                    "Last": 1,
                    "Done": True,
                }
            ],
            studies={"orth-1": _study_payload(UID_CT, "")},
        )
        first = orthanc_sync.sync_orthanc_studies(client=client)
        self.assertEqual(first["matched"], 1)

        # Second run resumes from cursor=1; FakeClient returns no new changes.
        second = orthanc_sync.sync_orthanc_studies(client=client)
        self.assertEqual(second, {"scanned": 0, "matched": 0, "skipped": 0})
        self.assertEqual(cache.get(orthanc_sync.CURSOR_CACHE_KEY), 1)


class OrthancSyncMultiTenantTest(TenantTestCase):
    """A study matching tenant A must not touch tenant B."""

    def setUp(self):
        cache.delete(orthanc_sync.CURSOR_CACHE_KEY)
        # tenant A == the FastTenantTestCase fast_test schema.
        self.schema_a = self.__class__.tenant.schema_name
        self.patient_a = Patient.objects.create(
            full_name="Ana A",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
        )
        self.study_a = DicomStudy.objects.create(
            patient=self.patient_a,
            study_instance_uid=UID_CT,
            accession_number=ACC_CT,
            modality="CT",
            study_date=datetime(2026, 5, 18, 14, 30, tzinfo=UTC),
        )
        # tenant B — separate schema, NO matching DicomStudy. Creating a Tenant
        # row provisions a schema, which django-tenants only allows from the
        # public schema; FastTenantTestCase leaves the connection on the
        # fast_test schema, so switch to public for the create.
        with schema_context(get_public_schema_name()):
            self.tenant_b = Tenant.objects.create(name="Clinic B", slug="clinicb")
        with schema_context(self.tenant_b.schema_name):
            self.patient_b = Patient.objects.create(
                full_name="Bea B",
                cpf="98765432100",
                birth_date=date(1990, 3, 1),
                gender="F",
            )
            # An unrelated study in B (different UID/accession).
            DicomStudy.objects.create(
                patient=self.patient_b,
                study_instance_uid="0.0.0.UNRELATED",
                accession_number="ACC-B-001",
                modality="MR",
                study_date=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
            )

    def tearDown(self):
        cache.delete(orthanc_sync.CURSOR_CACHE_KEY)
        try:
            self.tenant_b.delete(force_drop=True)
        except Exception:
            self.tenant_b.delete()

    def test_only_matching_tenant_updated(self):
        client = FakeOrthancClient(
            changes=[
                {
                    "Changes": [{"Seq": 1, "ChangeType": "StableStudy", "ID": "orth-1"}],
                    "Last": 1,
                    "Done": True,
                }
            ],
            studies={"orth-1": _study_payload(UID_CT, ACC_CT)},
        )
        # Force the public-schema fan-out path so both tenants are iterated.
        with patch("apps.core.tenancy.connection") as conn:
            conn.schema_name = "public"
            summary = orthanc_sync.sync_orthanc_studies(client=client)

        self.assertEqual(summary["matched"], 1)
        with schema_context(self.schema_a):
            self.study_a.refresh_from_db()
            self.assertEqual(self.study_a.orthanc_study_id, "orth-1")
        with schema_context(self.tenant_b.schema_name):
            b_orthanc_ids = list(DicomStudy.objects.values_list("orthanc_study_id", flat=True))
            self.assertEqual(b_orthanc_ids, [""])  # B untouched


class OrthancTaskInertTest(TenantTestCase):
    @override_settings(ORTHANC_URL="")
    def test_task_noops_when_url_empty(self):
        from apps.imaging.tasks import sync_orthanc_studies_task

        # The task imports sync_orthanc_studies into its own namespace.
        with patch("apps.imaging.tasks.sync_orthanc_studies") as mocked:
            result = sync_orthanc_studies_task()

        mocked.assert_not_called()
        self.assertTrue(result.get("inert"))
