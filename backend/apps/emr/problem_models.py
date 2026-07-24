"""Sprint E2 — problem-oriented EMR models.

New TENANT models that enrich the EMR toward a problem-oriented record:

* ``ProblemListItem`` — a FHIR ``Condition``-style entry on the patient problem
  list (governed CID-10 FK + legacy escape hatch, clinical/verification status,
  onset/abatement).
* ``Immunization`` — a FHIR ``Immunization``-style vaccination record (per PNI).

Both live in a NEW module (kept out of the already-large ``models.py``) and are
re-exported from ``models.py`` via a single ``from .problem_models import *``.

CID-10 governance mirrors E1 exactly: PostgreSQL does not enforce FK integrity
across schemas (tenant → public ``core.CID10Code``), so the FK is ``DO_NOTHING``
and deletion of a referenced code is blocked application-side by a ``pre_delete``
signal (``apps/emr/signals.py::protect_cid10_code_deletion_problems``), the exact
sibling of ``MedicalHistory.cid10``'s guard.
"""

import uuid

from django.db import models

from .models import Encounter, Patient


class ProblemListItem(models.Model):
    """A single active/inactive/resolved problem on a patient's problem list.

    Mirrors FHIR ``Condition``: a governed CID-10 code, a human-readable
    ``condition`` label, ``clinical_status`` (active/inactive/resolved) and
    ``verification_status`` (provisional/confirmed/refuted), plus onset/abatement
    dates. Optionally tied to the ``Encounter`` where the problem was recorded.
    """

    class ClinicalStatus(models.TextChoices):
        ACTIVE = "active", "Ativo"
        INACTIVE = "inactive", "Inativo"
        RESOLVED = "resolved", "Resolvido"

    class VerificationStatus(models.TextChoices):
        PROVISIONAL = "provisional", "Provisório"
        CONFIRMED = "confirmed", "Confirmado"
        REFUTED = "refuted", "Refutado"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="problem_list")
    # The problem is usually first recorded during an encounter, but persists
    # independently of it (longitudinal); SET_NULL keeps the problem if the
    # encounter is ever removed.
    encounter = models.ForeignKey(
        Encounter,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="problems",
    )
    condition = models.CharField(max_length=300)
    # E1-mirrored governed FK to the SHARED core.CID10Code catalog. DO_NOTHING +
    # the protect_cid10_code_deletion_problems pre_delete signal, exactly like
    # MedicalHistory.cid10 (PostgreSQL cannot enforce cross-schema FK integrity).
    cid10 = models.ForeignKey(
        "core.CID10Code",
        on_delete=models.DO_NOTHING,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="CID-10",
    )
    # Escape hatch, identical to MedicalHistory: preserve a raw CID that could not
    # be reconciled to a governed code (NEVER lose data).
    legacy_cid_text = models.CharField(
        max_length=10,
        blank=True,
        default="",
        help_text="Código CID-10 bruto não reconciliado com core.CID10Code.",
    )
    cid_unmatched = models.BooleanField(
        default=False,
        help_text="True quando legacy_cid_text não corresponde a nenhum CID10Code governado.",
    )
    clinical_status = models.CharField(
        max_length=20,
        choices=ClinicalStatus.choices,
        default=ClinicalStatus.ACTIVE,
        db_index=True,
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PROVISIONAL,
    )
    onset_date = models.DateField(null=True, blank=True)
    abatement_date = models.DateField(
        null=True,
        blank=True,
        help_text="Data de resolução/remissão do problema (FHIR abatement).",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Item da lista de problemas"
        verbose_name_plural = "Lista de problemas"
        indexes = [
            models.Index(fields=["patient", "clinical_status"]),
        ]

    @property
    def cid10_code(self) -> str:
        """Backward/interop-friendly string accessor (mirror MedicalHistory).

        Returns the governed FK's code when linked, else the raw legacy text.
        """
        if self.cid10_id:
            return self.cid10.code
        return self.legacy_cid_text

    @cid10_code.setter
    def cid10_code(self, value: str) -> None:
        code = (value or "").strip()
        if not code:
            self.cid10 = None
            self.legacy_cid_text = ""
            self.cid_unmatched = False
            return
        from apps.core.models import CID10Code

        match = CID10Code.objects.filter(code=code).first()
        if match is not None:
            self.cid10 = match
            self.legacy_cid_text = ""
            self.cid_unmatched = False
        else:
            self.cid10 = None
            self.legacy_cid_text = code
            self.cid_unmatched = True

    @property
    def is_active(self) -> bool:
        return self.clinical_status == self.ClinicalStatus.ACTIVE

    def __str__(self):
        return f"{self.condition} ({self.cid10_code or 'sem CID'}) — {self.clinical_status}"


class Immunization(models.Model):
    """A FHIR ``Immunization``-style vaccination record.

    Captures the immunobiological given, dose in the series, lot, date and an
    optional reference to the PNI (Programa Nacional de Imunizações) calendar.
    Longitudinal per patient — the immunization history is the ordered set of
    these rows for a patient.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="immunizations")
    # Immunobiological / vaccine name (e.g. "Tríplice viral (SCR)").
    immunobiological = models.CharField(max_length=200)
    # Dose within the series. Free text to accommodate PNI labels such as
    # "1ª dose", "reforço", "dose única".
    dose_number = models.CharField(max_length=50, blank=True, default="")
    lot = models.CharField(max_length=100, blank=True, default="")
    manufacturer = models.CharField(max_length=200, blank=True, default="")
    date = models.DateField()
    # Optional reference into the PNI vaccination calendar (code/label of the
    # calendar entry this dose fulfils). Free text — the governed PNI catalog is
    # out of scope for E2.
    pni_calendar_reference = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Referência ao calendário PNI que esta dose cumpre.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "immunobiological"]
        verbose_name = "Imunização"
        verbose_name_plural = "Imunizações"
        indexes = [
            models.Index(fields=["patient", "date"]),
        ]

    def __str__(self):
        return f"{self.immunobiological} {self.dose_number} ({self.date})".strip()
