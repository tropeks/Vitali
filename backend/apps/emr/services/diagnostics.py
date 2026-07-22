import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.models import AuditLog
from apps.emr.models import CriticalLabResult, LabSpecimen, LabSpecimenEvent

_TRANSITIONS = {
    LabSpecimen.Status.EXPECTED: {LabSpecimen.Status.COLLECTED, LabSpecimen.Status.REJECTED},
    LabSpecimen.Status.COLLECTED: {LabSpecimen.Status.RECEIVED, LabSpecimen.Status.REJECTED},
    LabSpecimen.Status.RECEIVED: {LabSpecimen.Status.PROCESSING, LabSpecimen.Status.REJECTED},
    LabSpecimen.Status.PROCESSING: {LabSpecimen.Status.STORED, LabSpecimen.Status.DISPOSED},
    LabSpecimen.Status.STORED: {LabSpecimen.Status.DISPOSED},
}


def transition_specimen(specimen, status, user, *, location="", reason="", instrument=None):
    correlation_id = str(uuid.uuid4())
    with transaction.atomic():
        specimen = LabSpecimen.objects.select_for_update().get(pk=specimen.pk)
        if status not in _TRANSITIONS.get(specimen.status, set()):
            raise ValidationError("Transição de amostra inválida.")
        old_status = specimen.status
        old_location = specimen.current_location
        specimen.status = status
        if location:
            specimen.current_location = location
        if status == LabSpecimen.Status.COLLECTED:
            specimen.collected_at = timezone.now()
            specimen.collected_by = user
        specimen.save()
        event = LabSpecimenEvent.objects.create(
            specimen=specimen,
            event_type=status,
            from_location=old_location,
            to_location=specimen.current_location,
            reason=reason,
            instrument=instrument,
            performed_by=user,
        )
        AuditLog.objects.create(
            user=user,
            action="lab_specimen_transition",
            resource_type="LabSpecimen",
            resource_id=str(specimen.id),
            new_data={
                "from": old_status,
                "to": status,
                "event_id": str(event.id),
                "correlation_id": correlation_id,
            },
        )
    return specimen


def open_critical_result(order_item, user):
    if order_item.abnormal_flag != order_item.AbnormalFlag.CRITICAL or not order_item.resulted_at:
        raise ValidationError("O item não contém resultado crítico liberado.")
    with transaction.atomic():
        critical, created = CriticalLabResult.objects.get_or_create(
            order_item=order_item, defaults={"detected_by": user}
        )
        if created:
            AuditLog.objects.create(
                user=user,
                action="critical_result_open",
                resource_type="CriticalLabResult",
                resource_id=str(critical.id),
                new_data={"order_item": str(order_item.id)},
            )
    return critical


def acknowledge_critical_result(critical, user, note):
    if not note.strip():
        raise ValidationError("A nota de reconhecimento é obrigatória.")
    with transaction.atomic():
        critical = CriticalLabResult.objects.select_for_update().get(pk=critical.pk)
        if critical.status == CriticalLabResult.Status.ACKNOWLEDGED:
            return critical
        critical.status = CriticalLabResult.Status.ACKNOWLEDGED
        critical.acknowledged_at = timezone.now()
        critical.acknowledged_by = user
        critical.acknowledgement_note = note
        critical.save()
        AuditLog.objects.create(
            user=user,
            action="critical_result_acknowledge",
            resource_type="CriticalLabResult",
            resource_id=str(critical.id),
            new_data={"order_item": str(critical.order_item_id)},
        )
    return critical
