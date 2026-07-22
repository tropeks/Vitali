"""
Phase 2 DICOM Study tracking primitive (E-012 partial).

This module is the storage + REST layer for DICOM studies — the *tracking*
side of the PACS integration. It does NOT include the OHIF viewer (frontend
component) or an Orthanc client (backend HTTP). Those are deploy-time
concerns; the tracking primitive shipped here works without them.

Once an Orthanc instance is deployed, an integration task can:
1. Receive Orthanc webhooks (or poll its REST API) when a study lands.
2. Look up the matching `DicomStudy` row by `accession_number` or
   `study_instance_uid` and set `orthanc_study_id` so the OHIF viewer can
   resolve the image URLs.

The split is intentional: clinics that already have an Orthanc / DICOM
gateway (most do) can register studies via this API and plug their viewer
into the resource id; clinics without an Orthanc deployment can still keep
a structured record of imaging studies referenced by their referrals /
reports.
"""

import uuid

from django.db import models

from apps.core.models import User
from apps.emr.models import ClinicalDocument, Encounter, LabOrderItem, Patient


class DicomStudy(models.Model):
    """One row per DICOM study (StudyInstanceUID is the natural key)."""

    # DICOM IOD Modality short codes (DICOM C.7.3.1.1.1, common subset).
    MODALITY_CHOICES = [
        ("CR", "Computed Radiography"),
        ("CT", "Computed Tomography"),
        ("DX", "Digital Radiography"),
        ("MG", "Mammography"),
        ("MR", "Magnetic Resonance"),
        ("NM", "Nuclear Medicine"),
        ("OT", "Other"),
        ("PT", "Positron Emission Tomography (PET)"),
        ("RF", "Radio Fluoroscopy"),
        ("US", "Ultrasound"),
        ("XA", "X-Ray Angiography"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="dicom_studies")
    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dicom_studies",
        help_text="Optional — the encounter that requested the study, if known.",
    )
    related_lab_item = models.ForeignKey(
        LabOrderItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="imaging_studies",
        help_text=(
            "Optional contextual link to a laboratory item for the same patient. "
            "The study remains a RIS/PACS resource, never a laboratory category."
        ),
    )
    report_document = models.OneToOneField(
        ClinicalDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dicom_study",
        help_text="Optional signed imaging report; content remains on the EMR document endpoint.",
    )

    # DICOM identity. StudyInstanceUID is mandatory and unique in DICOM; we
    # mirror that uniqueness here. AccessionNumber is the per-clinic order
    # number (DICOM tag 0008,0050) — usually unique but not guaranteed across
    # external integrators, so we make it indexed but not unique.
    study_instance_uid = models.CharField(max_length=128, unique=True, db_index=True)
    accession_number = models.CharField(max_length=64, blank=True, db_index=True)
    # Patient identity as encoded in DICOM.  The database schema already scopes
    # this pair to a tenant; keeping it on the study makes PACS ingestion able
    # to prove that pixels belong to the same patient as the Vitali FK.
    dicom_patient_id = models.CharField(max_length=64, blank=True, db_index=True)
    dicom_patient_id_issuer = models.CharField(max_length=64, blank=True)
    dicom_identity_verified = models.BooleanField(default=False, db_index=True)

    modality = models.CharField(max_length=4, choices=MODALITY_CHOICES, db_index=True)
    body_part_examined = models.CharField(max_length=64, blank=True)
    description = models.CharField(max_length=255, blank=True)
    study_date = models.DateTimeField()
    number_of_series = models.PositiveIntegerField(default=0)
    number_of_instances = models.PositiveIntegerField(default=0)

    # Populated once an Orthanc / PACS gateway has the actual pixel data. The
    # OHIF viewer URL is `<ohif-base>/viewer?StudyInstanceUIDs=<study-uid>`
    # when this field is set.
    orthanc_study_id = models.CharField(max_length=128, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="dicom_studies"
    )

    class Meta:
        ordering = ["-study_date"]
        indexes = [
            models.Index(fields=["patient", "-study_date"], name="img_pat_date_idx"),
            models.Index(fields=["modality", "-study_date"], name="img_mod_date_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.modality} — {self.body_part_examined or self.description} ({self.patient_id})"
        )

    def save(self, *args, **kwargs):
        # Enforce the default outside DRF too (admin, fixtures and order-flow
        # services all create studies). Integrations can still set an explicit
        # tenant-scoped DICOM identity before saving.
        if not self.dicom_patient_id and self.patient_id:
            self.dicom_patient_id = self.patient.medical_record_number
        return super().save(*args, **kwargs)

    @property
    def has_pixel_data(self) -> bool:
        """True only after Orthanc tags proved the patient identity."""
        return bool(self.orthanc_study_id and self.dicom_identity_verified)


class ImagingModality(models.Model):
    """Tenant-scoped DICOM node configuration exposed to infrastructure admins."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ae_title = models.CharField(max_length=16, unique=True)
    name = models.CharField(max_length=120)
    modality = models.CharField(max_length=4, choices=DicomStudy.MODALITY_CHOICES)
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=104)
    supports_mwl = models.BooleanField(default=True)
    supports_mpps = models.BooleanField(default=True)
    supports_storage_commitment = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True, db_index=True)
    last_echo_at = models.DateTimeField(null=True, blank=True)
    last_echo_ok = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.ae_title} — {self.name}"


class ModalityWorklistItem(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Agendado"
        IN_PROGRESS = "in_progress", "Em execução"
        COMPLETED = "completed", "Concluído"
        DISCONTINUED = "discontinued", "Descontinuado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    modality = models.ForeignKey(ImagingModality, on_delete=models.PROTECT, related_name="worklist")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="imaging_worklist")
    encounter = models.ForeignKey(Encounter, on_delete=models.SET_NULL, null=True, blank=True)
    accession_number = models.CharField(max_length=64, unique=True, db_index=True)
    requested_procedure_id = models.CharField(max_length=64)
    requested_procedure_description = models.CharField(max_length=255)
    scheduled_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SCHEDULED)
    study_instance_uid = models.CharField(max_length=128, blank=True, db_index=True)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="imaging_worklist_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.accession_number} — {self.requested_procedure_description}"


class DicomWorkflowEvent(models.Model):
    """Idempotent MPPS/Storage Commitment event journal."""

    class Type(models.TextChoices):
        MPPS_IN_PROGRESS = "mpps_in_progress", "MPPS em execução"
        MPPS_COMPLETED = "mpps_completed", "MPPS concluído"
        MPPS_DISCONTINUED = "mpps_discontinued", "MPPS descontinuado"
        STORAGE_COMMITMENT = "storage_commitment", "Storage Commitment"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    modality = models.ForeignKey(
        ImagingModality, on_delete=models.PROTECT, related_name="workflow_events"
    )
    worklist_item = models.ForeignKey(
        ModalityWorklistItem, on_delete=models.PROTECT, related_name="events"
    )
    event_uid = models.CharField(max_length=128)
    event_type = models.CharField(max_length=24, choices=Type.choices)
    payload = models.JSONField(default=dict, blank=True)
    success = models.BooleanField(default=True)
    error = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["modality", "event_uid"], name="img_workflow_event_unique"
            )
        ]

    def __str__(self):
        return f"{self.event_uid} ({self.event_type})"
