"""
Offline unit tests for OrthancClient — `requests` is mocked, no network.
"""

from __future__ import annotations

from unittest.mock import patch

import requests
from django.test import SimpleTestCase, override_settings

from apps.imaging.services.orthanc_client import OrthancClient, OrthancError


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


@override_settings(
    ORTHANC_URL="http://orthanc.example:8042",
    ORTHANC_USERNAME="vitali",
    ORTHANC_PASSWORD="secret",
    ORTHANC_HTTP_TIMEOUT=7,
)
class OrthancClientTest(SimpleTestCase):
    def test_get_changes_builds_request(self):
        client = OrthancClient()
        with patch("apps.imaging.services.orthanc_client.requests.get") as get:
            get.return_value = _Resp({"Changes": [], "Last": 0, "Done": True})
            client.get_changes(0, limit=50)
        args, kwargs = get.call_args
        self.assertEqual(args[0], "http://orthanc.example:8042/changes")
        self.assertEqual(kwargs["params"], {"since": 0, "limit": 50})
        self.assertEqual(kwargs["auth"], ("vitali", "secret"))
        self.assertEqual(kwargs["timeout"], 7)

    def test_timeout_raises_orthanc_error(self):
        client = OrthancClient()
        with patch("apps.imaging.services.orthanc_client.requests.get") as get:
            get.side_effect = requests.Timeout("slow")
            with self.assertRaises(OrthancError):
                client.get_changes(0)

    def test_http_error_raises_orthanc_error(self):
        client = OrthancClient()
        with patch("apps.imaging.services.orthanc_client.requests.get") as get:
            get.return_value = _Resp({}, status=500)
            with self.assertRaises(OrthancError):
                client.get_study("abc")

    def test_payload_helpers(self):
        study = {
            "MainDicomTags": {"StudyInstanceUID": "1.2.3", "AccessionNumber": "ACC-1"},
            "Series": ["a", "b"],
        }
        stats = {"CountSeries": 2, "CountInstances": "42"}
        self.assertEqual(OrthancClient.study_instance_uid(study), "1.2.3")
        self.assertEqual(OrthancClient.accession_number(study), "ACC-1")
        self.assertEqual(OrthancClient.series_count(study, stats), 2)
        self.assertEqual(OrthancClient.instance_count(study, stats), 42)

    def test_series_count_falls_back_to_series_list(self):
        study = {"Series": ["a", "b", "c"]}
        # No statistics → count the Series list.
        self.assertEqual(OrthancClient.series_count(study), 3)

    def test_payload_helpers_tolerate_missing_fields(self):
        self.assertEqual(OrthancClient.study_instance_uid({}), "")
        self.assertEqual(OrthancClient.accession_number({}), "")
        self.assertEqual(OrthancClient.series_count({}), 0)
        self.assertEqual(OrthancClient.instance_count({}), 0)

    def test_no_auth_when_username_blank(self):
        with override_settings(ORTHANC_USERNAME=""):
            client = OrthancClient()
            self.assertIsNone(client.auth)
