"""
FHIR R4 REST views.

Currently exposes:
- `GET /api/v1/fhir/metadata` — Capability Statement (machine-readable
  manifest of what this server supports, per FHIR R4 §3.2).
- `GET /api/v1/fhir/Patient/{id}/` — read one Patient as a FHIR resource.
- `GET /api/v1/fhir/Patient/?identifier=…|…&name=…&_count=…` — search,
  returning a FHIR Bundle (`type=searchset`).
- `GET /api/v1/fhir/Encounter/{id}/` — read one Encounter as a FHIR resource.
- `GET /api/v1/fhir/Encounter/?subject=Patient/{id}&status=…&_count=…` —
  Encounter search returning a Bundle.

The capability statement is intentionally public (FHIR clients must discover
support before authenticating). All resource endpoints are gated behind the
`fhir` module FeatureFlag + the `fhir.read` permission.
"""

from __future__ import annotations

import uuid

from django.http import Http404
from django.urls import reverse
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasPermission, ModuleRequiredPermission
from apps.emr.models import (
    Allergy,
    ClinicalDocument,
    Encounter,
    MedicalHistory,
    Patient,
    PatientInsurance,
    PrescriptionItem,
    Professional,
    VitalSigns,
)

from .permissions import SmartScopePermission, smart_patient_context
from .services.allergy_mapper import allergy_to_fhir
from .services.bundle import (
    parse_count,
    parse_offset,
    searchset_response,
)
from .services.condition_mapper import medical_history_to_fhir
from .services.coverage_mapper import patient_insurance_to_fhir
from .services.diagnostic_report_mapper import clinical_document_to_diagnostic_report
from .services.document_reference_mapper import clinical_document_to_document_reference
from .services.encounter_mapper import encounter_to_fhir
from .services.medication_request_mapper import prescription_item_to_fhir
from .services.observation_mapper import (
    vital_signs_observation,
    vital_signs_to_fhir_bundle,
)
from .services.patient_mapper import (
    SYSTEM_CPF,
    SYSTEM_MRN,
    patient_to_fhir,
)
from .services.practitioner_mapper import professional_to_fhir
from .services.service_request_mapper import clinical_document_to_fhir
from .services.smart import SUPPORTED_SCOPES

# SMART-on-FHIR OAuth URIs CapabilityStatement extension (smarthealthit.org).
_OAUTH_URIS_EXTENSION = "http://fhir-registry.smarthealthit.org/StructureDefinition/oauth-uris"
_SECURITY_SERVICE_SYSTEM = "http://terminology.hl7.org/CodeSystem/restful-security-service"

_FHIR_MODULE = ModuleRequiredPermission("fhir")
_SMART_SCOPE = SmartScopePermission()


def _ref_uuid(raw: str) -> uuid.UUID | None:
    """Parse a FHIR reference (`Patient/<uuid>`, `Encounter/<uuid>` or bare uuid).

    Returns ``None`` when malformed — callers translate that to an empty result
    set instead of letting a garbage id raise at queryset evaluation (500).
    """
    try:
        return uuid.UUID(raw.rsplit("/", 1)[-1])
    except (ValueError, AttributeError):
        return None


def _patient_scoped(qs, request, *, ref: str | None, field: str = "patient_id"):
    """Apply the `patient`/`subject` search filter AND SMART compartment confinement.

    ``ref`` is the raw query-param reference (or ``None``); ``field`` is the ORM
    path from the queryset's model to the patient id. When the request carries a
    patient-confined SMART token, the confinement filter is applied on top of the
    caller's filter — asking for another patient simply intersects to nothing, so
    a confined app cannot enumerate other patients' resources.
    """
    if ref:
        pid = _ref_uuid(ref)
        if pid is None:
            return qs.none()
        qs = qs.filter(**{field: pid})
    ctx = smart_patient_context(request)
    if ctx is not None:
        qs = qs.filter(**{field: ctx})
    return qs


def _context_allows(request, patient_pk) -> bool:
    """True unless a patient-confined SMART token points at a different patient."""
    ctx = smart_patient_context(request)
    return ctx is None or ctx == patient_pk


FHIR_VERSION = "4.0.1"
SERVER_VERSION = "1.0.0"


def _capability_security(request) -> dict:
    """Build the CapabilityStatement.rest.security block with SMART OAuth URIs.

    Advertises the SMART-on-FHIR profile per the conformance requirements: the
    ``oauth-uris`` extension points clients at the authorize/token endpoints, the
    service coding declares ``SMART-on-FHIR``, and the supported scopes are listed.
    """
    try:
        authorize_url = request.build_absolute_uri(reverse("fhir-smart-authorize"))
        token_url = request.build_absolute_uri(reverse("fhir-smart-token"))
    except Exception:
        authorize_url, token_url = "fhir/auth/authorize", "fhir/auth/token"
    return {
        "extension": [
            {
                "url": _OAUTH_URIS_EXTENSION,
                "extension": [
                    {"url": "authorize", "valueUri": authorize_url},
                    {"url": "token", "valueUri": token_url},
                ],
            }
        ],
        "service": [
            {
                "coding": [
                    {
                        "system": _SECURITY_SERVICE_SYSTEM,
                        "code": "SMART-on-FHIR",
                        "display": "SMART-on-FHIR",
                    }
                ],
                "text": "OAuth2 (SMART-on-FHIR authorization-code grant + PKCE)",
            }
        ],
        "description": (
            "SMART-on-FHIR authorization-code grant (PKCE). Bearer JWT + per-tenant "
            "module gate. Supported scopes: " + ", ".join(SUPPORTED_SCOPES)
        ),
    }


class CapabilityStatementView(APIView):
    """
    GET /api/v1/fhir/metadata — FHIR Capability Statement.

    Public so FHIR clients can negotiate capabilities before authenticating.
    The list of supported interactions reflects the current implementation,
    NOT the documented roadmap — it grows as resources land.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        rest_resources = [
            {
                "type": "Patient",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "identifier", "type": "token"},
                    {"name": "name", "type": "string"},
                ],
            },
            {
                "type": "Encounter",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "subject", "type": "reference"},
                    {"name": "status", "type": "token"},
                ],
            },
            {
                "type": "Practitioner",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "identifier", "type": "token"},
                    {"name": "name", "type": "string"},
                    {"name": "active", "type": "token"},
                ],
            },
            {
                "type": "AllergyIntolerance",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "patient", "type": "reference"},
                    {"name": "clinical-status", "type": "token"},
                ],
            },
            {
                "type": "MedicationRequest",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "patient", "type": "reference"},
                    {"name": "status", "type": "token"},
                ],
            },
            {
                "type": "Observation",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "patient", "type": "reference"},
                    {"name": "encounter", "type": "reference"},
                    {"name": "code", "type": "token"},
                ],
            },
            {
                "type": "Condition",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "patient", "type": "reference"},
                    {"name": "clinical-status", "type": "token"},
                    {"name": "category", "type": "token"},
                ],
            },
            {
                "type": "ServiceRequest",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "patient", "type": "reference"},
                    {"name": "status", "type": "token"},
                    {"name": "category", "type": "token"},
                ],
            },
            {
                "type": "DocumentReference",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "patient", "type": "reference"},
                ],
            },
            {
                "type": "DiagnosticReport",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "patient", "type": "reference"},
                    {"name": "status", "type": "token"},
                ],
            },
            {
                "type": "Coverage",
                "interaction": [{"code": "read"}, {"code": "search-type"}],
                "searchParam": [
                    {"name": "patient", "type": "reference"},
                    {"name": "status", "type": "token"},
                ],
            },
        ]
        return Response(
            {
                "resourceType": "CapabilityStatement",
                "status": "active",
                "date": "2026-06-20",
                "publisher": "Vitali",
                "kind": "instance",
                "software": {"name": "Vitali", "version": SERVER_VERSION},
                "fhirVersion": FHIR_VERSION,
                "format": ["application/fhir+json", "json"],
                "rest": [
                    {
                        "mode": "server",
                        "security": _capability_security(request),
                        "resource": rest_resources,
                    }
                ],
            }
        )


class PatientReadView(APIView):
    """GET /api/v1/fhir/Patient/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, patient_id: str):
        try:
            patient = Patient.objects.get(pk=patient_id)
        except (Patient.DoesNotExist, ValueError, Exception) as exc:
            # FHIR R4 §3.2.0.4 — read on a non-existent id returns 404 with an
            # OperationOutcome resource.
            if isinstance(exc, Patient.DoesNotExist) or isinstance(exc, ValueError):
                raise Http404 from exc
            raise
        if not _context_allows(request, patient.pk):
            raise Http404
        return Response(patient_to_fhir(patient))


class PatientSearchView(APIView):
    """
    GET /api/v1/fhir/Patient/?identifier=…|…&name=…&_count=…&_offset=…

    Search parameters supported:
    - `identifier` — `<system>|<value>` token. Accepted systems: the MRN URI
      and the Brazilian CPF OID (see `patient_mapper.SYSTEM_MRN/SYSTEM_CPF`).
    - `name` — case-insensitive substring match against `full_name`.
    - `_count` / `_offset` — page size (capped at 100, default 20) and page start.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        identifier = request.query_params.get("identifier")
        name = request.query_params.get("name")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = _patient_scoped(Patient.objects.all(), request, ref=None, field="pk")
        if identifier:
            qs = _filter_by_identifier(qs, identifier)
        if name:
            # full_name is encrypted at rest — SQL icontains cannot match the
            # ciphertext, so scan and match in Python (same pattern as the CPF
            # identifier lookup above). Interop endpoint, small table.
            needle = name.lower()
            matches = [p.pk for p in qs.iterator() if needle in (p.full_name or "").lower()]
            qs = qs.filter(pk__in=matches)

        total = qs.count()
        # full_name is encrypted → a SQL ORDER BY would sort ciphertext; sort the
        # decrypted values in Python to keep results in alphabetical name order.
        page = sorted(qs, key=lambda p: (p.full_name or "").lower())[offset : offset + count]
        entries = [
            {"fullUrl": _self_link(request, p), "resource": patient_to_fhir(p)} for p in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _filter_by_identifier(qs, value: str):
    """Apply a FHIR token-style `identifier` query (`<system>|<value>` or `<value>`)."""
    if "|" in value:
        system, ident = value.split("|", 1)
    else:
        system, ident = "", value
    if not ident:
        return qs.none()
    if system in ("", SYSTEM_MRN):
        return qs.filter(medical_record_number=ident)
    if system == SYSTEM_CPF:
        # CPF is encrypted at rest — full-table scan is the only correct path;
        # the lookup is rare (interop integrations) and the table is small.
        matches = [p.pk for p in qs.iterator() if (p.cpf or "") == ident]
        return qs.filter(pk__in=matches)
    return qs.none()


def _self_link(request, patient) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-patient-read", kwargs={"patient_id": patient.pk})
        )
    except Exception:
        return f"Patient/{patient.pk}"


class EncounterReadView(APIView):
    """GET /api/v1/fhir/Encounter/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, encounter_id: str):
        try:
            encounter = Encounter.objects.select_related("patient", "professional__user").get(
                pk=encounter_id
            )
        except (Encounter.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        if not _context_allows(request, encounter.patient_id):
            raise Http404
        return Response(encounter_to_fhir(encounter))


class EncounterSearchView(APIView):
    """
    GET /api/v1/fhir/Encounter/?subject=Patient/{uuid}&status=…&_count=…

    Supported search params:
    - `subject` — `Patient/<uuid>` or bare `<uuid>` filters by patient.
    - `patient` — alias of `subject` (FHIR allows both).
    - `status` — FHIR status code (`in-progress`, `finished`, `cancelled`).
      Translated back to the Vitali Encounter.status column.
    - `_count` — page size, capped at 100. Default 20.
    """

    _STATUS_REVERSE = {"in-progress": "open", "finished": "signed", "cancelled": "cancelled"}

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        subject = request.query_params.get("subject") or request.query_params.get("patient")
        fhir_status = request.query_params.get("status")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = _patient_scoped(
            Encounter.objects.select_related("patient", "professional__user").all(),
            request,
            ref=subject,
        )
        if fhir_status:
            internal = self._STATUS_REVERSE.get(fhir_status)
            if internal is None:
                qs = qs.none()
            else:
                qs = qs.filter(status=internal)

        total = qs.count()
        page = list(qs.order_by("-encounter_date")[offset : offset + count])
        entries = [
            {
                "fullUrl": _encounter_self_link(request, enc),
                "resource": encounter_to_fhir(enc),
            }
            for enc in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _encounter_self_link(request, encounter) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-encounter-read", kwargs={"encounter_id": encounter.pk})
        )
    except Exception:
        return f"Encounter/{encounter.pk}"


class PractitionerReadView(APIView):
    """GET /api/v1/fhir/Practitioner/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, practitioner_id: str):
        try:
            professional = Professional.objects.select_related("user").get(pk=practitioner_id)
        except (Professional.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        return Response(professional_to_fhir(professional))


class PractitionerSearchView(APIView):
    """
    GET /api/v1/fhir/Practitioner/?identifier=…|…&name=…&active=…&_count=…

    Supported search params:
    - `identifier` — `<system>|<value>` token. System is the council URI
      (`urn:vitali:council/crm`, `…/cro`, …); value is the council number.
      Bare `<value>` matches any council.
    - `name` — case-insensitive substring on the linked User's `full_name`.
    - `active` — `true` | `false`. FHIR encodes booleans as those literals.
    - `_count` — page size, capped at 100. Default 20.
    """

    _COUNCIL_PREFIX = "urn:vitali:council/"

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        identifier = request.query_params.get("identifier")
        name = request.query_params.get("name")
        active = request.query_params.get("active")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = Professional.objects.select_related("user").all()
        if identifier:
            qs = self._filter_by_identifier(qs, identifier)
        if name:
            qs = qs.filter(user__full_name__icontains=name)
        if active is not None:
            qs = qs.filter(is_active=active.lower() == "true")

        total = qs.count()
        page = list(qs.order_by("user__full_name")[offset : offset + count])
        entries = [
            {
                "fullUrl": _practitioner_self_link(request, p),
                "resource": professional_to_fhir(p),
            }
            for p in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)

    @classmethod
    def _filter_by_identifier(cls, qs, value: str):
        if "|" in value:
            system, ident = value.split("|", 1)
        else:
            system, ident = "", value
        if not ident:
            return qs.none()
        if system.startswith(cls._COUNCIL_PREFIX):
            council_type = system[len(cls._COUNCIL_PREFIX) :].upper()
            return qs.filter(council_type=council_type, council_number=ident)
        if system == "":
            return qs.filter(council_number=ident)
        return qs.none()


def _practitioner_self_link(request, professional) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-practitioner-read", kwargs={"practitioner_id": professional.pk})
        )
    except Exception:
        return f"Practitioner/{professional.pk}"


# ─── AllergyIntolerance ──────────────────────────────────────────────────────


class AllergyIntoleranceReadView(APIView):
    """GET /api/v1/fhir/AllergyIntolerance/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, allergy_id: str):
        try:
            allergy = Allergy.objects.select_related("patient").get(pk=allergy_id)
        except (Allergy.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        if not _context_allows(request, allergy.patient_id):
            raise Http404
        return Response(allergy_to_fhir(allergy))


class AllergyIntoleranceSearchView(APIView):
    """
    GET /api/v1/fhir/AllergyIntolerance/?patient=Patient/{id}&clinical-status=…&_count=…

    Search params:
    - `patient` — `Patient/<uuid>` or bare `<uuid>`.
    - `clinical-status` — `active` | `inactive` | `resolved`.
    - `_count` — page size, capped at 100. Default 20.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        patient = request.query_params.get("patient")
        clinical_status = request.query_params.get("clinical-status")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = _patient_scoped(Allergy.objects.select_related("patient").all(), request, ref=patient)
        if clinical_status in ("active", "inactive", "resolved"):
            qs = qs.filter(status=clinical_status)

        total = qs.count()
        page = list(qs.order_by("-created_at")[offset : offset + count])
        entries = [
            {
                "fullUrl": _allergy_self_link(request, a),
                "resource": allergy_to_fhir(a),
            }
            for a in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _allergy_self_link(request, allergy) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-allergy-read", kwargs={"allergy_id": allergy.pk})
        )
    except Exception:
        return f"AllergyIntolerance/{allergy.pk}"


# ─── MedicationRequest ───────────────────────────────────────────────────────
#
# A Vitali Prescription maps to N FHIR MedicationRequest resources (one per
# PrescriptionItem) — the FHIR id is the PrescriptionItem id.


class MedicationRequestReadView(APIView):
    """GET /api/v1/fhir/MedicationRequest/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, item_id: str):
        try:
            item = PrescriptionItem.objects.select_related(
                "prescription__patient",
                "prescription__prescriber",
                "prescription__encounter",
            ).get(pk=item_id)
        except (PrescriptionItem.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        if not _context_allows(request, item.prescription.patient_id):
            raise Http404
        return Response(prescription_item_to_fhir(item))


class MedicationRequestSearchView(APIView):
    """
    GET /api/v1/fhir/MedicationRequest/?patient=Patient/{id}&status=…&_count=…

    Search params:
    - `patient` — `Patient/<uuid>` or bare `<uuid>`.
    - `status` — FHIR MedicationRequest.status (`active`, `completed`,
      `cancelled`, `draft`).
    - `_count` — page size, capped at 100. Default 20.

    `status` is translated to the underlying Vitali Prescription.status set.
    """

    _STATUS_REVERSE = {
        "draft": ["draft"],
        "active": ["signed", "partially_dispensed"],
        "completed": ["dispensed"],
        "cancelled": ["cancelled"],
    }

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        patient = request.query_params.get("patient")
        fhir_status = request.query_params.get("status")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = PrescriptionItem.objects.select_related(
            "prescription__patient",
            "prescription__prescriber",
            "prescription__encounter",
        ).all()
        qs = _patient_scoped(qs, request, ref=patient, field="prescription__patient_id")
        if fhir_status:
            internal = self._STATUS_REVERSE.get(fhir_status)
            if internal is None:
                qs = qs.none()
            else:
                qs = qs.filter(prescription__status__in=internal)

        total = qs.count()
        page = list(qs.order_by("-prescription__created_at")[offset : offset + count])
        entries = [
            {
                "fullUrl": _medication_request_self_link(request, it),
                "resource": prescription_item_to_fhir(it),
            }
            for it in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _medication_request_self_link(request, item) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-medication-request-read", kwargs={"item_id": item.pk})
        )
    except Exception:
        return f"MedicationRequest/{item.pk}"


# ─── Observation ─────────────────────────────────────────────────────────────
#
# A Vitali VitalSigns row produces N FHIR Observation resources (one per
# vital, by LOINC code). The FHIR id is composed as `<encounter-id>-<loinc>`
# so it's stable across reads.


class ObservationReadView(APIView):
    """GET /api/v1/fhir/Observation/<encounter-id>-<loinc>/"""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, observation_id: str):
        if "_" not in observation_id:
            raise Http404
        encounter_id, loinc = observation_id.split("_", 1)
        try:
            vital = VitalSigns.objects.select_related("encounter__patient").get(
                encounter_id=encounter_id
            )
        except (VitalSigns.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        if not _context_allows(request, vital.encounter.patient_id):
            raise Http404
        resource = vital_signs_observation(vital, code=loinc)
        if resource is None:
            raise Http404("No observation for that LOINC code on this encounter.")
        return Response(resource)


class ObservationSearchView(APIView):
    """
    GET /api/v1/fhir/Observation/?patient=…&encounter=…&code=…&_count=…

    Search params:
    - `patient` — `Patient/<uuid>` or bare uuid (joins via encounter).
    - `encounter` — `Encounter/<uuid>` or bare uuid.
    - `code` — LOINC code (e.g. `8480-6` for systolic BP). Returns only the
      matching observation when both encounter and code are present.
    - `_count` / `_offset` — page size (capped at 100, default 50; vitals are
      dense) and page start.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        patient = request.query_params.get("patient")
        encounter = request.query_params.get("encounter")
        code = request.query_params.get("code")
        count = parse_count(request, default=50)
        offset = parse_offset(request)

        qs = _patient_scoped(
            VitalSigns.objects.select_related("encounter__patient").all(),
            request,
            ref=patient,
            field="encounter__patient_id",
        )
        if encounter:
            encounter_pk = _ref_uuid(encounter)
            qs = qs.filter(encounter_id=encounter_pk) if encounter_pk else qs.none()

        # A VitalSigns row expands into N Observations (one per LOINC code), so
        # the result-set size is only known after expansion. The per-patient
        # vitals table is small; materialise the full set for an accurate total
        # and a stable offset window.
        observations: list[dict] = []
        for vs in qs.order_by("-recorded_at"):
            if code:
                resource = vital_signs_observation(vs, code=code)
                if resource is not None:
                    observations.append(resource)
            else:
                observations.extend(vital_signs_to_fhir_bundle(vs))

        total = len(observations)
        page = observations[offset : offset + count]
        entries = [
            {"fullUrl": _observation_self_link(request, obs), "resource": obs} for obs in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _observation_self_link(request, observation: dict) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-observation-read", kwargs={"observation_id": observation["id"]})
        )
    except Exception:
        return f"Observation/{observation['id']}"


# ─── Condition ───────────────────────────────────────────────────────────────


class ConditionReadView(APIView):
    """GET /api/v1/fhir/Condition/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, condition_id: str):
        try:
            history = MedicalHistory.objects.select_related("patient").get(pk=condition_id)
        except (MedicalHistory.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        if not _context_allows(request, history.patient_id):
            raise Http404
        return Response(medical_history_to_fhir(history))


class ConditionSearchView(APIView):
    """
    GET /api/v1/fhir/Condition/?patient=…&clinical-status=…&category=…&_count=…

    Search params:
    - `patient` — `Patient/<uuid>` or bare uuid.
    - `clinical-status` — `active` | `resolved` (controlled rolls into active).
    - `category` — `problem-list-item` | `encounter-diagnosis`.
    - `_count` — page size, capped at 100. Default 20.
    """

    _CATEGORY_REVERSE = {
        "problem-list-item": ["chronic", "acute"],
        "encounter-diagnosis": ["surgical", "family"],
    }
    _CLINICAL_REVERSE = {
        "active": ["active", "controlled"],
        "resolved": ["resolved"],
    }

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        patient = request.query_params.get("patient")
        clinical_status = request.query_params.get("clinical-status")
        category = request.query_params.get("category")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = _patient_scoped(
            MedicalHistory.objects.select_related("patient").all(), request, ref=patient
        )
        if clinical_status:
            internal = self._CLINICAL_REVERSE.get(clinical_status)
            if internal is None:
                qs = qs.none()
            else:
                qs = qs.filter(status__in=internal)
        if category:
            internal_cats = self._CATEGORY_REVERSE.get(category)
            if internal_cats is None:
                qs = qs.none()
            else:
                qs = qs.filter(type__in=internal_cats)

        total = qs.count()
        page = list(qs.order_by("-created_at")[offset : offset + count])
        entries = [
            {
                "fullUrl": _condition_self_link(request, h),
                "resource": medical_history_to_fhir(h),
            }
            for h in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _condition_self_link(request, history) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-condition-read", kwargs={"condition_id": history.pk})
        )
    except Exception:
        return f"Condition/{history.pk}"


# ─── ServiceRequest ──────────────────────────────────────────────────────────
#
# ClinicalDocument rows with doc_type in {"referral", "exam_request"} surface
# as FHIR ServiceRequest. Other ClinicalDocument types are NOT exposed via
# this endpoint — they belong to different FHIR resource types (DocumentReference,
# DiagnosticReport, etc.) that are out of scope for this primitive.


_SERVICE_REQUEST_DOC_TYPES = ("referral", "exam_request")


class ServiceRequestReadView(APIView):
    """GET /api/v1/fhir/ServiceRequest/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, service_request_id: str):
        try:
            document = ClinicalDocument.objects.select_related(
                "encounter__patient", "encounter__professional__user"
            ).get(pk=service_request_id)
        except (ClinicalDocument.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        if document.doc_type not in _SERVICE_REQUEST_DOC_TYPES:
            raise Http404("ClinicalDocument type is not a ServiceRequest.")
        if not _context_allows(request, document.encounter.patient_id):
            raise Http404
        return Response(clinical_document_to_fhir(document))


class ServiceRequestSearchView(APIView):
    """
    GET /api/v1/fhir/ServiceRequest/?patient=…&status=…&category=…&_count=…

    Search params:
    - `patient` — `Patient/<uuid>` or bare uuid (joins via encounter).
    - `status` — FHIR status (`draft` | `active`). Internal mapping: `draft`
      → unsigned documents; `active` → signed documents.
    - `category` — `referral` | `exam_request`. Matches the underlying
      Vitali `doc_type`.
    - `_count` — page size, capped at 100. Default 20.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        patient = request.query_params.get("patient")
        fhir_status = request.query_params.get("status")
        category = request.query_params.get("category")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = ClinicalDocument.objects.select_related(
            "encounter__patient", "encounter__professional__user"
        ).filter(doc_type__in=_SERVICE_REQUEST_DOC_TYPES)

        qs = _patient_scoped(qs, request, ref=patient, field="encounter__patient_id")
        if fhir_status == "draft":
            qs = qs.filter(signed_at__isnull=True)
        elif fhir_status == "active":
            qs = qs.filter(signed_at__isnull=False)
        elif fhir_status is not None:
            qs = qs.none()
        if category in _SERVICE_REQUEST_DOC_TYPES:
            qs = qs.filter(doc_type=category)
        elif category is not None:
            qs = qs.none()

        total = qs.count()
        page = list(qs.order_by("-created_at")[offset : offset + count])
        entries = [
            {
                "fullUrl": _service_request_self_link(request, d),
                "resource": clinical_document_to_fhir(d),
            }
            for d in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _service_request_self_link(request, document) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-service-request-read", kwargs={"service_request_id": document.pk})
        )
    except Exception:
        return f"ServiceRequest/{document.pk}"


# ─── DocumentReference ───────────────────────────────────────────────────────
#
# ClinicalDocument rows with doc_type == "certificate" surface as FHIR
# DocumentReference (the document index/retrieval resource). Diagnostic findings
# ("report") map to DiagnosticReport; referrals/exam requests to ServiceRequest.


_DOCUMENT_REFERENCE_DOC_TYPES = ("certificate",)


class DocumentReferenceReadView(APIView):
    """GET /api/v1/fhir/DocumentReference/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, document_reference_id: str):
        try:
            document = ClinicalDocument.objects.select_related(
                "encounter__patient", "encounter__professional__user"
            ).get(pk=document_reference_id)
        except (ClinicalDocument.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        if document.doc_type not in _DOCUMENT_REFERENCE_DOC_TYPES:
            raise Http404("ClinicalDocument type is not a DocumentReference.")
        if not _context_allows(request, document.encounter.patient_id):
            raise Http404
        return Response(clinical_document_to_document_reference(document))


class DocumentReferenceSearchView(APIView):
    """
    GET /api/v1/fhir/DocumentReference/?patient=…&_count=…&_offset=…

    Search params:
    - `patient` / `subject` — `Patient/<uuid>` or bare uuid (joins via encounter).
    - `_count` / `_offset` — page size (capped at 100, default 20) and page start.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        patient = request.query_params.get("patient") or request.query_params.get("subject")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = ClinicalDocument.objects.select_related(
            "encounter__patient", "encounter__professional__user"
        ).filter(doc_type__in=_DOCUMENT_REFERENCE_DOC_TYPES)
        qs = _patient_scoped(qs, request, ref=patient, field="encounter__patient_id")

        total = qs.count()
        page = list(qs.order_by("-created_at")[offset : offset + count])
        entries = [
            {
                "fullUrl": _document_reference_self_link(request, d),
                "resource": clinical_document_to_document_reference(d),
            }
            for d in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _document_reference_self_link(request, document) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-document-reference-read", kwargs={"document_reference_id": document.pk})
        )
    except Exception:
        return f"DocumentReference/{document.pk}"


# ─── DiagnosticReport ────────────────────────────────────────────────────────
#
# ClinicalDocument rows with doc_type == "report" (Laudo) surface as FHIR
# DiagnosticReport.


_DIAGNOSTIC_REPORT_DOC_TYPES = ("report",)


class DiagnosticReportReadView(APIView):
    """GET /api/v1/fhir/DiagnosticReport/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, diagnostic_report_id: str):
        try:
            document = ClinicalDocument.objects.select_related(
                "encounter__patient", "encounter__professional__user"
            ).get(pk=diagnostic_report_id)
        except (ClinicalDocument.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        if document.doc_type not in _DIAGNOSTIC_REPORT_DOC_TYPES:
            raise Http404("ClinicalDocument type is not a DiagnosticReport.")
        if not _context_allows(request, document.encounter.patient_id):
            raise Http404
        return Response(clinical_document_to_diagnostic_report(document))


class DiagnosticReportSearchView(APIView):
    """
    GET /api/v1/fhir/DiagnosticReport/?patient=…&status=…&_count=…&_offset=…

    Search params:
    - `patient` / `subject` — `Patient/<uuid>` or bare uuid (joins via encounter).
    - `status` — FHIR status (`final` | `preliminary`). `final` → signed laudos;
      `preliminary` → unsigned.
    - `_count` / `_offset` — page size (capped at 100, default 20) and page start.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        patient = request.query_params.get("patient") or request.query_params.get("subject")
        fhir_status = request.query_params.get("status")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = ClinicalDocument.objects.select_related(
            "encounter__patient", "encounter__professional__user"
        ).filter(doc_type__in=_DIAGNOSTIC_REPORT_DOC_TYPES)
        qs = _patient_scoped(qs, request, ref=patient, field="encounter__patient_id")
        if fhir_status == "final":
            qs = qs.filter(signed_at__isnull=False)
        elif fhir_status == "preliminary":
            qs = qs.filter(signed_at__isnull=True)
        elif fhir_status is not None:
            qs = qs.none()

        total = qs.count()
        page = list(qs.order_by("-created_at")[offset : offset + count])
        entries = [
            {
                "fullUrl": _diagnostic_report_self_link(request, d),
                "resource": clinical_document_to_diagnostic_report(d),
            }
            for d in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _diagnostic_report_self_link(request, document) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-diagnostic-report-read", kwargs={"diagnostic_report_id": document.pk})
        )
    except Exception:
        return f"DiagnosticReport/{document.pk}"


# ─── Coverage ────────────────────────────────────────────────────────────────
#
# PatientInsurance (convênio) rows surface as FHIR Coverage.


class CoverageReadView(APIView):
    """GET /api/v1/fhir/Coverage/{id}/ — single-resource read."""

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request, coverage_id: str):
        try:
            insurance = PatientInsurance.objects.select_related("patient").get(pk=coverage_id)
        except (PatientInsurance.DoesNotExist, ValueError) as exc:
            raise Http404 from exc
        if not _context_allows(request, insurance.patient_id):
            raise Http404
        return Response(patient_insurance_to_fhir(insurance))


class CoverageSearchView(APIView):
    """
    GET /api/v1/fhir/Coverage/?patient=…&status=…&_count=…&_offset=…

    Search params:
    - `patient` / `beneficiary` — `Patient/<uuid>` or bare uuid.
    - `status` — FHIR Coverage.status (`active` | `cancelled`).
    - `_count` / `_offset` — page size (capped at 100, default 20) and page start.
    """

    def get_permissions(self):
        return [IsAuthenticated(), _FHIR_MODULE, HasPermission("fhir.read"), _SMART_SCOPE]

    def get(self, request):
        patient = request.query_params.get("patient") or request.query_params.get("beneficiary")
        fhir_status = request.query_params.get("status")
        count = parse_count(request)
        offset = parse_offset(request)

        qs = _patient_scoped(
            PatientInsurance.objects.select_related("patient").all(), request, ref=patient
        )
        if fhir_status == "active":
            qs = qs.filter(is_active=True)
        elif fhir_status == "cancelled":
            qs = qs.filter(is_active=False)
        elif fhir_status is not None:
            qs = qs.none()

        total = qs.count()
        page = list(qs.order_by("-is_active", "-created_at")[offset : offset + count])
        entries = [
            {
                "fullUrl": _coverage_self_link(request, c),
                "resource": patient_insurance_to_fhir(c),
            }
            for c in page
        ]
        return searchset_response(request, entries=entries, total=total, count=count, offset=offset)


def _coverage_self_link(request, insurance) -> str:
    try:
        return request.build_absolute_uri(
            reverse("fhir-coverage-read", kwargs={"coverage_id": insurance.pk})
        )
    except Exception:
        return f"Coverage/{insurance.pk}"
