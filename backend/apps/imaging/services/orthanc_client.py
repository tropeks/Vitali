"""
Thin HTTP client for the Orthanc PACS REST API (E-012 ingestion glue).

Only the read-only endpoints the ingestion poller needs are exposed:
`/changes` (the PACS-wide change feed) and `/studies/{id}` (study metadata).
The client is configured from settings (operator/trusted config — see
docs/IMAGING.md); it does NOT take user input and performs no writes.

All transport/HTTP failures are normalised to `OrthancError` so callers can
catch a single type and retry on the next tick.
"""

from __future__ import annotations

from typing import Any

import requests
from django.conf import settings


class OrthancError(Exception):
    """Raised for any Orthanc transport, timeout or HTTP-status failure."""


class OrthancClient:
    """Minimal Orthanc REST client (basic auth + per-request timeout)."""

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.ORTHANC_URL).rstrip("/")
        username = username if username is not None else settings.ORTHANC_USERNAME
        password = password if password is not None else settings.ORTHANC_PASSWORD
        self.auth = (username, password) if username else None
        self.timeout = timeout if timeout is not None else settings.ORTHANC_HTTP_TIMEOUT

    # ─── Transport ────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.get(url, params=params, auth=self.auth, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise OrthancError(f"Orthanc GET {path} failed: {exc}") from exc
        except ValueError as exc:  # invalid JSON body
            raise OrthancError(f"Orthanc GET {path} returned invalid JSON: {exc}") from exc

    # ─── Endpoints ──────────────────────────────────────────────────────────────

    def get_changes(self, since: int, limit: int = 100) -> dict[str, Any]:
        """GET ``/changes?since=&limit=`` → ``{Changes:[...], Last:int, Done:bool}``."""
        return self._get("/changes", params={"since": since, "limit": limit})

    def get_study(self, orthanc_id: str) -> dict[str, Any]:
        """GET ``/studies/{id}`` → study payload (MainDicomTags + Series list)."""
        return self._get(f"/studies/{orthanc_id}")

    def get_study_statistics(self, orthanc_id: str) -> dict[str, Any]:
        """GET ``/studies/{id}/statistics`` → ``{CountSeries, CountInstances, ...}``.

        The plain ``/studies/{id}`` payload does not carry instance counts, so we
        ask Orthanc for the dedicated statistics resource when we need them.
        """
        return self._get(f"/studies/{orthanc_id}/statistics")

    # ─── Payload helpers ──────────────────────────────────────────────────────

    @staticmethod
    def study_instance_uid(study: dict[str, Any]) -> str:
        return (study.get("MainDicomTags") or {}).get("StudyInstanceUID", "")

    @staticmethod
    def accession_number(study: dict[str, Any]) -> str:
        return (study.get("MainDicomTags") or {}).get("AccessionNumber", "")

    @staticmethod
    def patient_id(study: dict[str, Any]) -> str:
        """DICOM PatientID (0010,0020), normally in PatientMainDicomTags."""
        patient_tags = study.get("PatientMainDicomTags") or {}
        return str(
            patient_tags.get("PatientID")
            or (study.get("MainDicomTags") or {}).get("PatientID")
            or ""
        ).strip()

    @staticmethod
    def issuer_of_patient_id(study: dict[str, Any]) -> str:
        """DICOM IssuerOfPatientID (0010,0021), blank when not supplied."""
        patient_tags = study.get("PatientMainDicomTags") or {}
        return str(
            patient_tags.get("IssuerOfPatientID")
            or (study.get("MainDicomTags") or {}).get("IssuerOfPatientID")
            or ""
        ).strip()

    @staticmethod
    def series_count(study: dict[str, Any], statistics: dict[str, Any] | None = None) -> int:
        """Series count, preferring the statistics resource over the Series list."""
        if statistics:
            n = _safe_int(statistics.get("CountSeries"))
            if n:
                return n
        return len(study.get("Series") or [])

    @staticmethod
    def instance_count(study: dict[str, Any], statistics: dict[str, Any] | None = None) -> int:
        """Total instance count from the ``/statistics`` resource (0 if absent).

        Orthanc's plain ``/studies/{id}`` payload carries no instance count, so
        callers should pass the ``/studies/{id}/statistics`` dict. Best-effort.
        """
        if statistics:
            return _safe_int(statistics.get("CountInstances"))
        raw = study.get("CountInstances")
        return _safe_int(raw)


def _safe_int(raw: Any) -> int:
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0
