from django.contrib import admin

from .models import DicomStudy


@admin.register(DicomStudy)
class DicomStudyAdmin(admin.ModelAdmin):
    list_display = (
        "modality",
        "body_part_examined",
        "patient",
        "related_lab_item",
        "report_document",
        "study_date",
        "has_pixel_data",
    )
    list_filter = ("modality",)
    search_fields = (
        "study_instance_uid",
        "accession_number",
        "orthanc_study_id",
        "patient__full_name",
    )
    ordering = ("-study_date",)
    raw_id_fields = ("patient", "encounter", "related_lab_item", "report_document")
    readonly_fields = ("id", "created_at", "created_by", "has_pixel_data")
