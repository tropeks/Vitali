from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import AuditLog
from apps.imaging.models import DicomWorkflowEvent, ModalityWorklistItem


def record_echo(modality, ok, user):
    modality.last_echo_at = timezone.now()
    modality.last_echo_ok = ok
    modality.save(update_fields=["last_echo_at", "last_echo_ok"])
    AuditLog.objects.create(
        user=user,
        action="dicom_c_echo",
        resource_type="ImagingModality",
        resource_id=str(modality.id),
        new_data={"ok": ok, "ae_title": modality.ae_title},
    )
    return modality


def apply_workflow_event(worklist, modality, event_uid, event_type, payload, user):
    if worklist.modality_id != modality.id:
        raise ValidationError("A modalidade não corresponde ao item MWL.")
    mapping = {
        DicomWorkflowEvent.Type.MPPS_IN_PROGRESS: ModalityWorklistItem.Status.IN_PROGRESS,
        DicomWorkflowEvent.Type.MPPS_COMPLETED: ModalityWorklistItem.Status.COMPLETED,
        DicomWorkflowEvent.Type.MPPS_DISCONTINUED: ModalityWorklistItem.Status.DISCONTINUED,
    }
    with transaction.atomic():
        worklist = ModalityWorklistItem.objects.select_for_update().get(pk=worklist.pk)
        event, created = DicomWorkflowEvent.objects.get_or_create(
            modality=modality,
            event_uid=event_uid,
            defaults={
                "worklist_item": worklist,
                "event_type": event_type,
                "payload": payload,
            },
        )
        if not created:
            return event, False
        if event_type in mapping:
            worklist.status = mapping[event_type]
            if payload.get("study_instance_uid"):
                worklist.study_instance_uid = payload["study_instance_uid"]
            worklist.save(update_fields=["status", "study_instance_uid"])
        AuditLog.objects.create(
            user=user,
            action="dicom_workflow_event",
            resource_type="ModalityWorklistItem",
            resource_id=str(worklist.id),
            new_data={"event_id": str(event.id), "event_type": event_type},
        )
    return event, created
