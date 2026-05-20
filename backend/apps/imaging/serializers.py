"""Serializers for the imaging (DICOM Study tracking) module."""

from __future__ import annotations

from rest_framework import serializers

from .models import DicomStudy


class DicomStudySerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    has_pixel_data = serializers.BooleanField(read_only=True)
    modality_display = serializers.CharField(source="get_modality_display", read_only=True)

    class Meta:
        model = DicomStudy
        fields = [
            "id",
            "patient",
            "patient_name",
            "encounter",
            "study_instance_uid",
            "accession_number",
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
            "created_at",
        ]


class DicomStudyCreateSerializer(serializers.ModelSerializer):
    """Distinct from the read serializer so the API surface for creation is explicit."""

    class Meta:
        model = DicomStudy
        fields = [
            "patient",
            "encounter",
            "study_instance_uid",
            "accession_number",
            "modality",
            "body_part_examined",
            "description",
            "study_date",
            "number_of_series",
            "number_of_instances",
            "orthanc_study_id",
        ]


class DicomStudyOrthancPatchSerializer(serializers.Serializer):
    """Patch payload for backfilling the Orthanc UID once the PACS has the study."""

    orthanc_study_id = serializers.CharField(max_length=128)
    number_of_series = serializers.IntegerField(required=False, min_value=0)
    number_of_instances = serializers.IntegerField(required=False, min_value=0)
