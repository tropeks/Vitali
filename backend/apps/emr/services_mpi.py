"""Minimal MPI matching with no automatic merge side effects."""

import hashlib
import hmac
import re
import unicodedata
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from .models import DuplicatePatientCandidate, Patient, PatientIdentifier


def _normalize(value: str) -> str:
    return re.sub(
        r"[^a-z0-9]",
        "",
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower(),
    )


def identifier_digest(system: str, issuer: str, value: str) -> str:
    """Keyed digest permits exact matching without persisting identifier plaintext."""

    key = getattr(settings, "MPI_IDENTIFIER_HMAC_KEY", settings.SECRET_KEY).encode()
    message = "\x1f".join((system.strip().lower(), issuer.strip().lower(), _normalize(value)))
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


class DuplicatePatientDetectionService:
    """Creates review candidates only; never mutates either patient."""

    @transaction.atomic
    def detect(self, patient: Patient) -> list[DuplicatePatientCandidate]:
        signals: dict[uuid.UUID, set[str]] = {}
        identifiers = PatientIdentifier.objects.filter(patient=patient, status="active")
        for identifier in identifiers:
            matches = PatientIdentifier.objects.filter(
                system=identifier.system,
                issuer=identifier.issuer,
                value_digest=identifier.value_digest,
                status="active",
            ).exclude(patient=patient)
            for match in matches:
                signals.setdefault(match.patient_id, set()).add(f"identifier:{identifier.system}")

        normalized_name = _normalize(patient.full_name)
        for other in Patient.objects.filter(birth_date=patient.birth_date).exclude(pk=patient.pk):
            if normalized_name and _normalize(other.full_name) == normalized_name:
                signals.setdefault(other.id, set()).add("name_and_birth_date")

        candidates = []
        for other_id, reasons in signals.items():
            patient_a_id, patient_b_id = sorted((patient.id, other_id), key=str)
            exact_identifier = any(reason.startswith("identifier:") for reason in reasons)
            score = Decimal("1.0000") if exact_identifier else Decimal("0.8000")
            candidate, _ = DuplicatePatientCandidate.objects.update_or_create(
                patient_a_id=patient_a_id,
                patient_b_id=patient_b_id,
                defaults={"score": score, "reasons": sorted(reasons)},
            )
            candidates.append(candidate)
        return candidates
