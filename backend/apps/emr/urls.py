from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AppointmentViewSet,
    AvailableSlotsView,
    ClinicalDocumentViewSet,
    ClinicalFormResponseViewSet,
    ClinicalFormTemplateViewSet,
    DuplicatePatientCandidateViewSet,
    EncounterAddendumViewSet,
    EncounterViewSet,
    LabDeltaAlertViewSet,
    LabOrderViewSet,
    LabTestViewSet,
    MedicationAdministrationViewSet,
    NursingAssessmentViewSet,
    PatientIdentifierViewSet,
    PatientViewSet,
    PrescriptionItemViewSet,
    PrescriptionViewSet,
    ProfessionalViewSet,
    ScheduleConfigViewSet,
    SOAPNoteViewSet,
    VitalSignsViewSet,
    WaitingRoomView,
)
from .views_adt import (
    AdmissionEventViewSet,
    AdmissionViewSet,
    BedViewSet,
    InpatientUnitViewSet,
    RoomViewSet,
)
from .views_blood_donor import BloodBagSerologyViewSet, BloodDonorViewSet
from .views_bloodbank import BloodBagViewSet, BloodComponentViewSet
from .views_cid10 import CID10AcceptView, CID10SuggestView
from .views_diagnostics import CriticalLabResultViewSet, LabInstrumentViewSet, LabSpecimenViewSet
from .views_emergency import EmergencyEncounterViewSet, RiskClassificationViewSet
from .views_lab_report import LabReportPDFView, LabReportSignView
from .views_lis import LabIntegrationMessageViewSet, LabOrderORMView, LISInboundView
from .views_pdf import PrescriptionPDFView
from .views_problems import AllergyViewSet, ImmunizationViewSet, ProblemListItemViewSet
from .views_reconciliation import MedicationReconciliationViewSet, OrderSetViewSet
from .views_sae import (
    NursingCareplanInterventionViewSet,
    NursingCareplanViewSet,
    NursingDiagnosisViewSet,
    NursingEvolutionViewSet,
    NursingPrescriptionItemViewSet,
)
from .views_safety import (
    AcknowledgeDeteriorationAlertView,
    AcknowledgeNoShowRiskView,
    AcknowledgeSafetyAlertView,
    DeteriorationAlertsView,
    NoShowRiskView,
    PrescriptionItemSafetyCheckView,
)
from .views_scribe import ScribeStartView, ScribeStatusView, ScribeTranscribeView
from .views_setup import WizardProfessionalSetupView, WizardStatusView
from .views_surgery import (
    AnestheticEventViewSet,
    AnestheticRecordViewSet,
    OperatingRoomViewSet,
    PacuAssessmentViewSet,
    PacuRecordViewSet,
    RoomTurnoverViewSet,
    SurgicalCaseViewSet,
    SurgicalChecklistViewSet,
    SurgicalMaterialViewSet,
    SurgicalProcedureViewSet,
    SurgicalTeamMemberViewSet,
    SurgicalTimeViewSet,
)
from .views_transfusion import CrossMatchViewSet, TransfusionRequestViewSet
from .views_transfusion_admin import (
    TransfusionAdministrationViewSet,
    TransfusionChecarView,
    TransfusionReactionViewSet,
)
from .views_waitlist import WaitlistDetailView, WaitlistViewSet

router = DefaultRouter()
router.register("patients", PatientViewSet, basename="patient")
router.register("patient-identifiers", PatientIdentifierViewSet, basename="patient-identifier")
router.register(
    "mpi/duplicate-candidates", DuplicatePatientCandidateViewSet, basename="duplicate-candidate"
)
router.register("professionals", ProfessionalViewSet, basename="professional")
router.register("appointments", AppointmentViewSet, basename="appointment")
router.register("schedule-configs", ScheduleConfigViewSet, basename="schedule-config")
router.register("encounters", EncounterViewSet, basename="encounter")
router.register("soap-notes", SOAPNoteViewSet, basename="soap-note")
router.register("vital-signs", VitalSignsViewSet, basename="vital-signs")
router.register("documents", ClinicalDocumentViewSet, basename="document")
router.register(
    "clinical-form-templates", ClinicalFormTemplateViewSet, basename="clinical-form-template"
)
router.register(
    "clinical-form-responses", ClinicalFormResponseViewSet, basename="clinical-form-response"
)
router.register("encounter-addenda", EncounterAddendumViewSet, basename="encounter-addendum")
router.register("lab-tests", LabTestViewSet, basename="lab-test")
router.register("lab-orders", LabOrderViewSet, basename="lab-order")
router.register("lab-delta-alerts", LabDeltaAlertViewSet, basename="lab-delta-alert")
router.register("lab-integrations", LabIntegrationMessageViewSet, basename="lab-integration")
router.register("lab-instruments", LabInstrumentViewSet, basename="lab-instrument")
router.register("lab-specimens", LabSpecimenViewSet, basename="lab-specimen")
router.register("critical-lab-results", CriticalLabResultViewSet, basename="critical-lab-result")
router.register("prescriptions", PrescriptionViewSet, basename="prescription")
router.register("prescription-items", PrescriptionItemViewSet, basename="prescription-item")
router.register("emar", MedicationAdministrationViewSet, basename="emar")
router.register("nursing-assessments", NursingAssessmentViewSet, basename="nursing-assessment")
# ── N2: executable SAE domain (diagnóstico → planejamento → intervenção → prescrição → evolução)
router.register("nursing-diagnoses", NursingDiagnosisViewSet, basename="nursing-diagnosis")
router.register("nursing-careplans", NursingCareplanViewSet, basename="nursing-careplan")
router.register(
    "nursing-care-interventions",
    NursingCareplanInterventionViewSet,
    basename="nursing-care-intervention",
)
router.register(
    "nursing-prescription-items",
    NursingPrescriptionItemViewSet,
    basename="nursing-prescription-item",
)
router.register("nursing-evolutions", NursingEvolutionViewSet, basename="nursing-evolution")
router.register("problems", ProblemListItemViewSet, basename="problem")
router.register("allergies", AllergyViewSet, basename="allergy")
router.register("immunizations", ImmunizationViewSet, basename="immunization")
router.register(
    "medication-reconciliations",
    MedicationReconciliationViewSet,
    basename="medication-reconciliation",
)
router.register("order-sets", OrderSetViewSet, basename="order-set")
# ── L1: ADT/Leitos — estrutura física (unidade → quarto → leito)
router.register("inpatient-units", InpatientUnitViewSet, basename="inpatient-unit")
router.register("rooms", RoomViewSet, basename="room")
router.register("beds", BedViewSet, basename="bed")
# ── L2: ADT/Leitos — admissão/internação + log de eventos ADT (append-only)
router.register("admissions", AdmissionViewSet, basename="admission")
router.register("admission-events", AdmissionEventViewSet, basename="admission-event")
# ── C1: Centro Cirúrgico — sala → caso cirúrgico → procedimento (TUSS)
router.register("operating-rooms", OperatingRoomViewSet, basename="operating-room")
router.register("surgical-cases", SurgicalCaseViewSet, basename="surgical-case")
router.register("surgical-procedures", SurgicalProcedureViewSet, basename="surgical-procedure")
# ── C3: Centro Cirúrgico — equipe (CRUD) + tempos + checklist OMS (append-only)
router.register("surgical-team", SurgicalTeamMemberViewSet, basename="surgical-team")
router.register("surgical-times", SurgicalTimeViewSet, basename="surgical-time")
router.register("surgical-checklists", SurgicalChecklistViewSet, basename="surgical-checklist")
# ── C6: Centro Cirúrgico — materiais / OPME + consumo de sala (rastreabilidade)
router.register("surgical-materials", SurgicalMaterialViewSet, basename="surgical-material")
# ── CC2: Centro Cirúrgico — ficha anestésica + timeline do ato anestésico
router.register("anesthetic-records", AnestheticRecordViewSet, basename="anesthetic-record")
router.register("anesthetic-events", AnestheticEventViewSet, basename="anesthetic-event")
# ── CS2: Centro Cirúrgico — SRPA / PACU (recuperação pós-anestésica)
router.register("pacu-records", PacuRecordViewSet, basename="pacu-record")
router.register("pacu-assessments", PacuAssessmentViewSet, basename="pacu-assessment")
# ── CS3: Centro Cirúrgico — turnover de sala (higienização/preparo entre cirurgias)
router.register("room-turnovers", RoomTurnoverViewSet, basename="room-turnover")
# ── E2: PS/Emergência — boletim de atendimento + classificação de risco (Manchester)
router.register("emergency-encounters", EmergencyEncounterViewSet, basename="emergency-encounter")
router.register("risk-classifications", RiskClassificationViewSet, basename="risk-classification")
# ── H1: Banco de Sangue/Hemoterapia — catálogo de hemocomponentes + estoque de bolsas
router.register("blood-components", BloodComponentViewSet, basename="blood-component")
router.register("blood-bags", BloodBagViewSet, basename="blood-bag")
# H2 — doador + triagem sorológica (RDC 34)
router.register("blood-donors", BloodDonorViewSet, basename="blood-donor")
router.register("blood-bag-serologies", BloodBagSerologyViewSet, basename="blood-bag-serology")
# H3 — requisição transfusional + prova de compatibilidade
router.register("transfusion-requests", TransfusionRequestViewSet, basename="transfusion-request")
router.register("crossmatches", CrossMatchViewSet, basename="crossmatch")
# H4 — checagem beira-leito + administração + reação transfusional (hemovigilância)
router.register(
    "transfusion-administrations",
    TransfusionAdministrationViewSet,
    basename="transfusion-administration",
)
router.register(
    "transfusion-reactions", TransfusionReactionViewSet, basename="transfusion-reaction"
)

urlpatterns = (
    [
        path("lab-integrations/inbound/", LISInboundView.as_view(), name="lis-inbound"),
        # H4 — checagem beira-leito da requisição transfusional
        path(
            "transfusion-requests/<uuid:pk>/checar/",
            TransfusionChecarView.as_view(),
            name="transfusion-request-checar",
        ),
        path("lab-orders/<uuid:order_id>/orm/", LabOrderORMView.as_view(), name="lab-order-orm"),
        path(
            "lab-orders/<uuid:order_id>/report/sign/",
            LabReportSignView.as_view(),
            name="lab-report-sign",
        ),
        path(
            "lab-orders/<uuid:order_id>/report/pdf/",
            LabReportPDFView.as_view(),
            name="lab-report-pdf",
        ),
    ]
    + router.urls
    + [
        path("professionals/<uuid:professional_id>/available-slots/", AvailableSlotsView.as_view()),
        path("waiting-room/", WaitingRoomView.as_view()),
        # S-054: Onboarding wizard setup
        path(
            "emr/setup/professional/",
            WizardProfessionalSetupView.as_view(),
            name="wizard-professional-setup",
        ),
        path("emr/setup/status/", WizardStatusView.as_view(), name="wizard-status"),
        # S-063: AI Prescription Safety
        path(
            "prescription-items/<uuid:item_id>/safety-check/",
            PrescriptionItemSafetyCheckView.as_view(),
            name="prescription-safety-check",
        ),
        path(
            "safety-alerts/<uuid:alert_id>/acknowledge/",
            AcknowledgeSafetyAlertView.as_view(),
            name="safety-alert-acknowledge",
        ),
        # Clinical-deterioration wedge (D3): NEWS2 early-warning surface
        path(
            "deterioration-alerts/",
            DeteriorationAlertsView.as_view(),
            name="deterioration-alerts",
        ),
        path(
            "deterioration-alerts/<uuid:alert_id>/acknowledge/",
            AcknowledgeDeteriorationAlertView.as_view(),
            name="deterioration-alert-acknowledge",
        ),
        # No-show prediction wedge (N3): front-desk risk surface
        path("no-show-risk/", NoShowRiskView.as_view(), name="no-show-risk"),
        path(
            "no-show-risk/<uuid:risk_id>/acknowledge/",
            AcknowledgeNoShowRiskView.as_view(),
            name="no-show-risk-acknowledge",
        ),
        # S-064: AI CID-10 Suggester
        path(
            "encounters/<uuid:encounter_id>/cid10-suggest/",
            CID10SuggestView.as_view(),
            name="cid10-suggest",
        ),
        path(
            "encounters/<uuid:encounter_id>/cid10-accept/",
            CID10AcceptView.as_view(),
            name="cid10-accept",
        ),
        # S-065: Prescription PDF
        path(
            "prescriptions/<uuid:prescription_id>/pdf/",
            PrescriptionPDFView.as_view(),
            name="prescription-pdf",
        ),
        # S-066: Appointment Cancellation Waitlist
        path("waitlist/", WaitlistViewSet.as_view(), name="waitlist-list"),
        path("waitlist/<uuid:entry_id>/", WaitlistDetailView.as_view(), name="waitlist-detail"),
        # S-069: AI Clinical Scribe
        path(
            "encounters/<uuid:encounter_id>/scribe/start/",
            ScribeStartView.as_view(),
            name="scribe-start",
        ),
        path(
            "encounters/<uuid:encounter_id>/scribe/status/",
            ScribeStatusView.as_view(),
            name="scribe-status",
        ),
        # S-073: Whisper API Transcription Fallback
        path(
            "encounters/<uuid:encounter_id>/scribe/transcribe/",
            ScribeTranscribeView.as_view(),
            name="scribe-transcribe",
        ),
    ]
)
