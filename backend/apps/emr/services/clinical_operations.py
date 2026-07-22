from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.emr.models import MedicationAdministration, PrescriptionItem


class MedicationAdministrationService:
    """Transactional eMAR gate enforcing order, pharmacy and identity integrity."""

    @staticmethod
    @transaction.atomic
    def record(*, prescription_item, scheduled_at, status, user, **details):
        item = (
            PrescriptionItem.objects.select_for_update()
            .select_related("prescription__encounter", "prescription__patient", "drug")
            .get(pk=prescription_item.pk)
        )
        if item.prescription.status not in {"signed", "partially_dispensed", "dispensed"}:
            raise ValidationError({"prescription_item": "A ordem deve estar assinada."})
        validation = getattr(item.prescription, "pharmacist_validation", None)
        if validation is None or validation.status != "approved":
            raise ValidationError(
                {"prescription_item": "Validação farmacêutica aprovada é obrigatória."}
            )
        if (
            status != MedicationAdministration.Status.GIVEN
            and not details.get("reason", "").strip()
        ):
            raise ValidationError({"reason": "Informe o motivo para dose não administrada."})
        if item.drug.is_controlled and details.get("witness") is None:
            raise ValidationError({"witness": "Medicamento controlado exige testemunha."})
        if details.get("witness") == user:
            raise ValidationError({"witness": "A testemunha deve ser outro profissional."})
        details.setdefault("dose_amount", item.dose_amount)
        details.setdefault("dose_unit", item.dose_unit)
        details.setdefault("route", item.route)
        return MedicationAdministration.objects.create(
            prescription_item=item,
            encounter=item.prescription.encounter,
            patient=item.prescription.patient,
            scheduled_at=scheduled_at,
            status=status,
            administered_by=user,
            **details,
        )
