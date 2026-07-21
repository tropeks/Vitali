"""
Integration tests for the Orthanc → Vitali push webhook (E-012).

No network: a ``FakeOrthancClient`` stands in for ``OrthancClient`` so the
webhook's ``ingest_one_study`` call returns canned study metadata. Covers the
acceptance criterion (study lands in Orthanc → ``orthanc_study_id`` backfilled),
shared-secret auth, the inert / unconfigured guards, and malformed input.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.models import FeatureFlag
from apps.emr.models import Patient
from apps.imaging.models import DicomStudy
from apps.imaging.services.orthanc_client import OrthancClient, OrthancError
from apps.test_utils import TenantTestCase

WEBHOOK_URL = "/api/v1/imaging/orthanc/webhook/"
SECRET = "t0p-s3cret-webhook"
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
    """In-memory stand-in: serves canned ``/studies/{id}`` payloads."""

    def __init__(self, *, studies=None, raises=None):
        # Skip super().__init__ — no settings/network needed.
        self._studies = studies or {}
        self._raises = set(raises or ())

    def get_study(self, orthanc_id):
        if orthanc_id in self._raises:
            raise OrthancError(f"simulated 404 for {orthanc_id}")
        return self._studies[orthanc_id]["study"]

    def get_study_statistics(self, orthanc_id):
        if orthanc_id in self._raises:
            raise OrthancError(f"simulated 404 for {orthanc_id}")
        return self._studies[orthanc_id]["statistics"]


@override_settings(ORTHANC_URL="http://orthanc:8042", ORTHANC_WEBHOOK_SECRET=SECRET)
class OrthancWebhookTest(TenantTestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.defaults["SERVER_NAME"] = self.__class__.domain.domain
        FeatureFlag.objects.update_or_create(
            tenant=self.__class__.tenant,
            module_key="imaging",
            defaults={"is_enabled": True},
        )
        self.patient = Patient.objects.create(
            full_name="Ana Maria Souza",
            cpf="12345678909",
            birth_date=date(1985, 7, 14),
            gender="F",
        )
        self.study = DicomStudy.objects.create(
            patient=self.patient,
            study_instance_uid=UID_CT,
            accession_number=ACC_CT,
            modality="CT",
            study_date=datetime(2026, 5, 18, 14, 30, tzinfo=UTC),
        )

    def _post(self, body, *, secret=SECRET):
        headers = {}
        if secret is not None:
            headers["HTTP_X_ORTHANC_WEBHOOK_SECRET"] = secret
        return self.client.post(WEBHOOK_URL, body, format="json", **headers)

    def _patch_client(self, **kwargs):
        fake = FakeOrthancClient(**kwargs)
        return patch(
            "apps.imaging.services.orthanc_sync.OrthancClient",
            return_value=fake,
        )

    # ─── Acceptance criterion ──────────────────────────────────────────────────

    def test_webhook_backfills_orthanc_study_id(self):
        """DICOM lands in Orthanc → webhook backfills orthanc_study_id + counts."""
        with self._patch_client(
            studies={"orth-1": _study_payload(UID_CT, ACC_CT, n_series=4, n_instances=120)}
        ):
            resp = self._post({"orthanc_study_id": "orth-1"})

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["outcome"], "matched")
        self.study.refresh_from_db()
        self.assertEqual(self.study.orthanc_study_id, "orth-1")
        self.assertTrue(self.study.has_pixel_data)
        self.assertEqual(self.study.number_of_series, 4)
        self.assertEqual(self.study.number_of_instances, 120)

    def test_webhook_accepts_orthanc_native_id_key(self):
        """Orthanc's Lua hook may send the raw ``ID`` key — accept it too."""
        with self._patch_client(studies={"orth-2": _study_payload(UID_CT, "")}):
            resp = self._post({"ID": "orth-2"})

        self.assertEqual(resp.status_code, 200, resp.data)
        self.study.refresh_from_db()
        self.assertEqual(self.study.orthanc_study_id, "orth-2")

    def test_webhook_no_matching_row_is_skipped(self):
        with self._patch_client(studies={"orth-x": _study_payload("9.9.9.UNKNOWN", "NO-SUCH-ACC")}):
            resp = self._post({"orthanc_study_id": "orth-x"})

        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["outcome"], "skipped")
        self.study.refresh_from_db()
        self.assertEqual(self.study.orthanc_study_id, "")

    # ─── Auth (shared secret) ──────────────────────────────────────────────────

    def test_webhook_rejects_missing_secret(self):
        resp = self._post({"orthanc_study_id": "orth-1"}, secret=None)
        self.assertEqual(resp.status_code, 403)
        self.study.refresh_from_db()
        self.assertEqual(self.study.orthanc_study_id, "")

    def test_webhook_rejects_wrong_secret(self):
        resp = self._post({"orthanc_study_id": "orth-1"}, secret="wrong")
        self.assertEqual(resp.status_code, 403)

    @override_settings(ORTHANC_WEBHOOK_SECRET="")
    def test_webhook_refuses_when_secret_unset(self):
        resp = self._post({"orthanc_study_id": "orth-1"}, secret="anything")
        self.assertEqual(resp.status_code, 503)

    # ─── Inert / malformed ─────────────────────────────────────────────────────

    @override_settings(ORTHANC_URL="")
    def test_webhook_inert_when_url_empty(self):
        with self._patch_client(studies={"orth-1": _study_payload(UID_CT, "")}) as mocked:
            resp = self._post({"orthanc_study_id": "orth-1"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get("inert"))
        mocked.assert_not_called()

    def test_webhook_rejects_malformed_id(self):
        resp = self._post({"orthanc_study_id": "../../etc/passwd"})
        self.assertEqual(resp.status_code, 400)

    def test_webhook_rejects_missing_id(self):
        resp = self._post({})
        self.assertEqual(resp.status_code, 400)

    def test_webhook_502_when_study_unfetchable(self):
        with self._patch_client(studies={}, raises={"orth-gone"}):
            resp = self._post({"orthanc_study_id": "orth-gone"})
        self.assertEqual(resp.status_code, 502)
