from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AppointmentViewSet,
    AvailableSlotsView,
    ClinicalDocumentViewSet,
    EncounterViewSet,
    LabOrderViewSet,
    LabTestViewSet,
    PatientViewSet,
    PrescriptionItemViewSet,
    PrescriptionViewSet,
    ProfessionalViewSet,
    ScheduleConfigViewSet,
    SOAPNoteViewSet,
    VitalSignsViewSet,
    WaitingRoomView,
)
from .views_cid10 import CID10AcceptView, CID10SuggestView
from .views_lab_report import LabReportPDFView, LabReportSignView
from .views_lis import LabIntegrationMessageViewSet, LabOrderORMView, LISInboundView
from .views_pdf import PrescriptionPDFView
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
from .views_waitlist import WaitlistDetailView, WaitlistViewSet

router = DefaultRouter()
router.register("patients", PatientViewSet, basename="patient")
router.register("professionals", ProfessionalViewSet, basename="professional")
router.register("appointments", AppointmentViewSet, basename="appointment")
router.register("schedule-configs", ScheduleConfigViewSet, basename="schedule-config")
router.register("encounters", EncounterViewSet, basename="encounter")
router.register("soap-notes", SOAPNoteViewSet, basename="soap-note")
router.register("vital-signs", VitalSignsViewSet, basename="vital-signs")
router.register("documents", ClinicalDocumentViewSet, basename="document")
router.register("lab-tests", LabTestViewSet, basename="lab-test")
router.register("lab-orders", LabOrderViewSet, basename="lab-order")
router.register("lab-integrations", LabIntegrationMessageViewSet, basename="lab-integration")
router.register("prescriptions", PrescriptionViewSet, basename="prescription")
router.register("prescription-items", PrescriptionItemViewSet, basename="prescription-item")

urlpatterns = (
    [
        path("lab-integrations/inbound/", LISInboundView.as_view(), name="lis-inbound"),
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
