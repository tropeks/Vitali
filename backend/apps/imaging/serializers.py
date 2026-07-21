"""Serializers for the imaging (DICOM Study tracking) module."""

from __future__ import annotations

from rest_framework import serializers

from .models import DicomStudy


class DicomStudySerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    has_pixel_data = serializers.BooleanField(read_only=True)
    modality_display = serializers.CharField(source="get_modality_display", read_only=True)
    related_lab_order = serializers.UUIDField(
        source="related_lab_item.order_id", read_only=True, allow_null=True
    )
    report_status = serializers.SerializerMethodField()

    class Meta:
        model = DicomStudy
        fields = [
            "id",
            "patient",
            "patient_name",
            "encounter",
            "related_lab_item",
            "related_lab_order",
            "report_document",
            "report_status",
            "study_instance_uid",
            "accession_number",
            "dicom_patient_id",
            "dicom_patient_id_issuer",
            "dicom_identity_verified",
            "modality",
            "modality_display",
            "body_part_examined",
            "description",
            "study_date",
            "number_of_series",
            "number_of_instances",
            "orthanc_study_id",
            "has_pixel_data",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "patient_name",
            "modality_display",
            "has_pixel_data",
            "dicom_identity_verified",
            "created_at",
        ]

    def get_report_status(self, obj):
        report = obj.report_document
        if report is None:
            return None
        return {
            "id": str(report.id),
            "doc_type": report.doc_type,
            "is_signed": report.is_signed,
            "signed_at": report.signed_at,
            "signed_by": report.signed_by_id,
            "signature_hash": report.signature_hash,
            "is_icp_brasil": report.is_icp_brasil,
        }


class DicomStudyCreateSerializer(serializers.ModelSerializer):
    """Distinct from the read serializer so the API surface for creation is explicit."""

    class Meta:
        model = DicomStudy
        fields = [
            "patient",
            "encounter",
            "related_lab_item",
            "report_document",
            "study_instance_uid",
            "accession_number",
            "dicom_patient_id",
            "dicom_patient_id_issuer",
            "modality",
            "body_part_examined",
            "description",
            "study_date",
            "number_of_series",
            "number_of_instances",
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        patient = attrs.get("patient")
        encounter = attrs.get("encounter")
        lab_item = attrs.get("related_lab_item")
        report = attrs.get("report_document")

        # The MRN is Vitali's canonical DICOM PatientID unless an integration
        # explicitly supplies another tenant-scoped identifier.
        if patient and not attrs.get("dicom_patient_id"):
            attrs["dicom_patient_id"] = patient.medical_record_number

        if encounter and encounter.patient_id != patient.id:
            raise serializers.ValidationError(
                {"encounter": "O atendimento não pertence ao paciente informado."}
            )
        if lab_item and lab_item.order.patient_id != patient.id:
            raise serializers.ValidationError(
                {"related_lab_item": "O item laboratorial não pertence ao paciente informado."}
            )
        if report:
            if report.doc_type != "report":
                raise serializers.ValidationError(
                    {"report_document": "O documento vinculado deve ser um laudo."}
                )
            if report.encounter.patient_id != patient.id:
                raise serializers.ValidationError(
                    {"report_document": "O laudo não pertence ao paciente informado."}
                )
            if encounter and report.encounter_id != encounter.id:
                raise serializers.ValidationError(
                    {"report_document": "O laudo não pertence ao atendimento informado."}
                )
        return attrs


class DicomStudyOrthancPatchSerializer(serializers.Serializer):
    """Patch payload for backfilling the Orthanc UID once the PACS has the study."""

    orthanc_study_id = serializers.CharField(max_length=128)
