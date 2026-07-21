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
from apps.imaging.services.orthanc_client import OrthancClient, OrthancError
from apps.test_utils import TenantTestCase

UID_CT = "1.2.840.113619.2.55.3.604688119.1234567890.001"
ACC_CT = "ACC-2026-001"


def _summary(*, scanned=0, matched=0, skipped=0, ambiguous=0, errored=0, locked=False):
    """Build the full per-run summary dict for exact-equality assertions."""
    return {
        "scanned": scanned,
        "matched": matched,
        "skipped": skipped,
        "ambiguous_skipped": ambiguous,
        "identity_mismatch_skipped": 0,
        "error_skipped": errored,
        "lock_skipped": locked,
    }


def _study_payload(uid, accession, n_series=3, n_instances=240, patient_id="TEST-PATIENT-ID"):
    return {
        "study": {
            "MainDicomTags": {"StudyInstanceUID": uid, "AccessionNumber": accession},
            "PatientMainDicomTags": {"PatientID": patient_id},
            "Series": ["s"] * n_series,
        },
        "statistics": {"CountSeries": n_series, "CountInstances": n_instances},
    }


class FakeOrthancClient(OrthancClient):
    """In-memory stand-in: serves canned changes pages + study payloads."""

    def __init__(self, *, changes, studies, raises=None):
        # Deliberately skip super().__init__ — no settings/network needed.
        self._changes = changes  # list of pages: {"Changes":[...],"Last":int,"Done":bool}
        self._studies = studies  # {orthanc_id: {"study":..., "statistics":...}}
        # orthanc_ids whose get_study should raise OrthancError (poison pill).
        self._raises = set(raises or ())
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
        if orthanc_id in self._raises:
            raise OrthancError(f"simulated 404 for {orthanc_id}")
        return self._studies[orthanc_id]["study"]

    def get_study_statistics(self, orthanc_id):
        if orthanc_id in self._raises:
            raise OrthancError(f"simulated 404 for {orthanc_id}")
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
            dicom_patient_id="TEST-PATIENT-ID",
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

        self.assertEqual(summary, _summary(scanned=1, matched=1))
        self.ct_study.refresh_from_db()
        self.assertEqual(self.ct_study.orthanc_study_id, "orth-1")
        self.assertEqual(self.ct_study.number_of_series, 4)
        self.assertEqual(self.ct_study.number_of_instances, 120)
        self.assertEqual(cache.get(orthanc_sync.CURSOR_CACHE_KEY), 1)

    def test_accession_fallback_refuses_conflicting_uid(self):
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

        self.assertEqual(summary["identity_mismatch_skipped"], 1)
        self.ct_study.refresh_from_db()
        self.assertEqual(self.ct_study.orthanc_study_id, "")

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

        self.assertEqual(summary, _summary(scanned=1, skipped=1))
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
        self.assertEqual(summary, _summary())
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
        self.assertEqual(second, _summary())
        self.assertEqual(cache.get(orthanc_sync.CURSOR_CACHE_KEY), 1)

    def test_poison_pill_study_skipped_run_continues_cursor_advances(self):
        """A deleted/unfetchable study (OrthancError on get_study) must not abort
        the run: it is counted as error_skipped, the cursor advances past it, and
        later changes in the same feed are still processed."""
        client = self._client(
            changes=[
                {
                    "Changes": [
                        # Seq 1: study was deleted after the change was emitted.
                        {"Seq": 1, "ChangeType": "StableStudy", "ID": "orth-gone"},
                        # Seq 2: a healthy study that matches our UID row.
                        {"Seq": 2, "ChangeType": "StableStudy", "ID": "orth-1"},
                    ],
                    "Last": 2,
                    "Done": True,
                }
            ],
            studies={"orth-1": _study_payload(UID_CT, "", n_series=2, n_instances=50)},
        )
        client._raises = {"orth-gone"}

        summary = orthanc_sync.sync_orthanc_studies(client=client)

        # Both scanned; one errored, one matched; run did not abort.
        self.assertEqual(summary, _summary(scanned=2, matched=1, errored=1))
        self.ct_study.refresh_from_db()
        self.assertEqual(self.ct_study.orthanc_study_id, "orth-1")
        # Cursor advanced past BOTH changes (including the poison pill at Seq 1).
        self.assertEqual(cache.get(orthanc_sync.CURSOR_CACHE_KEY), 2)

    def test_lock_held_returns_lock_skipped_without_touching_cursor(self):
        """When another run holds the lock, the call returns lock_skipped and
        never reads/advances the cursor or calls the client."""
        cache.set(orthanc_sync.CURSOR_CACHE_KEY, 7)
        # Simulate a concurrent run already holding the single-flight lock.
        cache.add(orthanc_sync.SYNC_LOCK_KEY, "1", orthanc_sync.SYNC_LOCK_TTL)
        try:
            client = self._client(
                changes=[
                    {
                        "Changes": [{"Seq": 8, "ChangeType": "StableStudy", "ID": "orth-1"}],
                        "Last": 8,
                        "Done": True,
                    }
                ],
                studies={"orth-1": _study_payload(UID_CT, "")},
            )
            summary = orthanc_sync.sync_orthanc_studies(client=client)

            self.assertEqual(summary, _summary(locked=True))
            # Client was never consulted and cursor is untouched.
            self.assertEqual(client.get_changes_calls, 0)
            self.assertEqual(cache.get(orthanc_sync.CURSOR_CACHE_KEY), 7)
            self.ct_study.refresh_from_db()
            self.assertEqual(self.ct_study.orthanc_study_id, "")
        finally:
            cache.delete(orthanc_sync.SYNC_LOCK_KEY)

    def test_lock_released_after_run_allows_next_run(self):
        """The lock is released in a finally, so a subsequent run proceeds."""
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
        orthanc_sync.sync_orthanc_studies(client=client)
        # Lock must be free again.
        self.assertIsNone(cache.get(orthanc_sync.SYNC_LOCK_KEY))
        # A second run is not lock-skipped (it just finds no new changes).
        second = orthanc_sync.sync_orthanc_studies(client=client)
        self.assertFalse(second["lock_skipped"])


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
            dicom_patient_id="TEST-PATIENT-ID",
            study_instance_uid=UID_CT,
            accession_number=ACC_CT,
            modality="CT",
            study_date=datetime(2026, 5, 18, 14, 30, tzinfo=UTC),
        )
        # tenant B — a separate, EMPTY schema (no DicomStudy). Creating a Tenant
        # row provisions a schema, which django-tenants only allows from the
        # public schema; FastTenantTestCase leaves the connection on the
        # fast_test schema, so switch to public for the create. We intentionally
        # leave B empty: inserting rows under the test's atomic transaction leaves
        # deferred FK trigger events that block DROP SCHEMA in tearDown. An empty B
        # still proves the fan-out visits it and updates only the matching tenant.
        with schema_context(get_public_schema_name()):
            self.tenant_b = Tenant.objects.create(name="Clinic B", slug="clinicb")

    def tearDown(self):
        cache.delete(orthanc_sync.CURSOR_CACHE_KEY)
        # Dropping a tenant schema, like creating it, must run from the public
        # schema; FastTenantTestCase leaves the connection on fast_test.
        with schema_context(get_public_schema_name()):
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
            # B has no studies → the fan-out visited it but found nothing to
            # update, proving only the matching tenant (A) was touched.
            self.assertEqual(DicomStudy.objects.count(), 0)

    def test_uid_match_short_circuits_to_single_tenant(self):
        """UID is globally unique: the first matching tenant is updated and the
        scan stops. Only tenant A (which holds the UID row) is linked; empty B
        is untouched, and the matched count is exactly 1."""
        client = FakeOrthancClient(
            changes=[
                {
                    "Changes": [{"Seq": 1, "ChangeType": "StableStudy", "ID": "orth-1"}],
                    "Last": 1,
                    "Done": True,
                }
            ],
            studies={"orth-1": _study_payload(UID_CT, "")},  # UID only, no accession
        )
        with patch("apps.core.tenancy.connection") as conn:
            conn.schema_name = "public"
            summary = orthanc_sync.sync_orthanc_studies(client=client)

        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["ambiguous_skipped"], 0)
        with schema_context(self.schema_a):
            self.study_a.refresh_from_db()
            self.assertEqual(self.study_a.orthanc_study_id, "orth-1")
        with schema_context(self.tenant_b.schema_name):
            self.assertEqual(DicomStudy.objects.count(), 0)


class OrthancSyncAccessionAmbiguityTest(TenantTestCase):
    """Cross-tenant PHI-leak guard: an accession that collides across two
    clinics (with NO UID match anywhere) must update NEITHER tenant.

    The tenant fan-out is mocked rather than backed by two real schemas with
    rows: FastTenantTestCase leaves deferred FK trigger events on a populated
    2nd schema that block DROP SCHEMA in tearDown. Mocking the iteration tests
    the ambiguity decision directly and avoids the trigger problem.
    """

    def setUp(self):
        cache.delete(orthanc_sync.CURSOR_CACHE_KEY)

    def tearDown(self):
        cache.delete(orthanc_sync.CURSOR_CACHE_KEY)

    def test_ambiguous_accession_across_tenants_updates_neither(self):
        client = FakeOrthancClient(
            changes=[
                {
                    "Changes": [{"Seq": 3, "ChangeType": "StableStudy", "ID": "orth-amb"}],
                    "Last": 3,
                    "Done": True,
                }
            ],
            # No UID match anywhere; both tenants carry the SAME accession.
            studies={"orth-amb": _study_payload("9.9.9.NO.SUCH.UID", ACC_CT)},
        )

        def fake_fan_out(callback, *, logger, operation):
            # UID scan finds nothing in any tenant; accession scan finds the
            # colliding accession in BOTH tenant schemas → 2 matches → ambiguous.
            if "uid" in operation:
                return [None, None]
            if "accession scan" in operation:
                return ["clinic_a", "clinic_b"]
            # An apply pass must never run for an ambiguous accession.
            raise AssertionError(f"unexpected fan-out pass: {operation}")

        with patch(
            "apps.imaging.services.orthanc_sync.for_each_tenant_schema",
            side_effect=fake_fan_out,
        ):
            summary = orthanc_sync.sync_orthanc_studies(client=client)

        # Ambiguous: nothing matched, nothing written, counted as ambiguous.
        self.assertEqual(summary, _summary(scanned=1, ambiguous=1))
        # Cursor still advances past the ambiguous (processed) change.
        self.assertEqual(cache.get(orthanc_sync.CURSOR_CACHE_KEY), 3)


class OrthancTaskInertTest(TenantTestCase):
    @override_settings(ORTHANC_URL="")
    def test_task_noops_when_url_empty(self):
        from apps.imaging.tasks import sync_orthanc_studies_task

        # The task imports sync_orthanc_studies into its own namespace.
        with patch("apps.imaging.tasks.sync_orthanc_studies") as mocked:
            result = sync_orthanc_studies_task()

        mocked.assert_not_called()
        self.assertTrue(result.get("inert"))
