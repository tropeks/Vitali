from django.urls import path

from .views import (
    AllergyIntoleranceReadView,
    AllergyIntoleranceSearchView,
    CapabilityStatementView,
    ConditionReadView,
    ConditionSearchView,
    CoverageReadView,
    CoverageSearchView,
    DiagnosticReportReadView,
    DiagnosticReportSearchView,
    DocumentReferenceReadView,
    DocumentReferenceSearchView,
    EncounterReadView,
    EncounterSearchView,
    MedicationRequestReadView,
    MedicationRequestSearchView,
    ObservationReadView,
    ObservationSearchView,
    PatientReadView,
    PatientSearchView,
    PractitionerReadView,
    PractitionerSearchView,
    ServiceRequestReadView,
    ServiceRequestSearchView,
)
from .views_smart import AuthorizeView, SmartConfigurationView, TokenView

urlpatterns = [
    path("fhir/metadata", CapabilityStatementView.as_view(), name="fhir-metadata"),
    path("fhir/Patient/", PatientSearchView.as_view(), name="fhir-patient-search"),
    path(
        "fhir/Patient/<uuid:patient_id>/",
        PatientReadView.as_view(),
        name="fhir-patient-read",
    ),
    path("fhir/Encounter/", EncounterSearchView.as_view(), name="fhir-encounter-search"),
    path(
        "fhir/Encounter/<uuid:encounter_id>/",
        EncounterReadView.as_view(),
        name="fhir-encounter-read",
    ),
    path(
        "fhir/Practitioner/",
        PractitionerSearchView.as_view(),
        name="fhir-practitioner-search",
    ),
    path(
        "fhir/Practitioner/<uuid:practitioner_id>/",
        PractitionerReadView.as_view(),
        name="fhir-practitioner-read",
    ),
    path(
        "fhir/AllergyIntolerance/",
        AllergyIntoleranceSearchView.as_view(),
        name="fhir-allergy-search",
    ),
    path(
        "fhir/AllergyIntolerance/<uuid:allergy_id>/",
        AllergyIntoleranceReadView.as_view(),
        name="fhir-allergy-read",
    ),
    path(
        "fhir/MedicationRequest/",
        MedicationRequestSearchView.as_view(),
        name="fhir-medication-request-search",
    ),
    path(
        "fhir/MedicationRequest/<uuid:item_id>/",
        MedicationRequestReadView.as_view(),
        name="fhir-medication-request-read",
    ),
    path(
        "fhir/Observation/",
        ObservationSearchView.as_view(),
        name="fhir-observation-search",
    ),
    path(
        "fhir/Observation/<str:observation_id>/",
        ObservationReadView.as_view(),
        name="fhir-observation-read",
    ),
    path(
        "fhir/Condition/",
        ConditionSearchView.as_view(),
        name="fhir-condition-search",
    ),
    path(
        "fhir/Condition/<uuid:condition_id>/",
        ConditionReadView.as_view(),
        name="fhir-condition-read",
    ),
    path(
        "fhir/ServiceRequest/",
        ServiceRequestSearchView.as_view(),
        name="fhir-service-request-search",
    ),
    path(
        "fhir/ServiceRequest/<uuid:service_request_id>/",
        ServiceRequestReadView.as_view(),
        name="fhir-service-request-read",
    ),
    path(
        "fhir/DocumentReference/",
        DocumentReferenceSearchView.as_view(),
        name="fhir-document-reference-search",
    ),
    path(
        "fhir/DocumentReference/<uuid:document_reference_id>/",
        DocumentReferenceReadView.as_view(),
        name="fhir-document-reference-read",
    ),
    path(
        "fhir/DiagnosticReport/",
        DiagnosticReportSearchView.as_view(),
        name="fhir-diagnostic-report-search",
    ),
    path(
        "fhir/DiagnosticReport/<uuid:diagnostic_report_id>/",
        DiagnosticReportReadView.as_view(),
        name="fhir-diagnostic-report-read",
    ),
    path(
        "fhir/Coverage/",
        CoverageSearchView.as_view(),
        name="fhir-coverage-search",
    ),
    path(
        # PatientInsurance uses an integer PK (unlike the UUID-keyed clinical
        # models), so Coverage ids are integers.
        "fhir/Coverage/<int:coverage_id>/",
        CoverageReadView.as_view(),
        name="fhir-coverage-read",
    ),
    # ─── SMART-on-FHIR / OAuth2 ──────────────────────────────────────────────
    path(
        "fhir/.well-known/smart-configuration",
        SmartConfigurationView.as_view(),
        name="fhir-smart-configuration",
    ),
    path("fhir/auth/authorize", AuthorizeView.as_view(), name="fhir-smart-authorize"),
    path("fhir/auth/token", TokenView.as_view(), name="fhir-smart-token"),
]
