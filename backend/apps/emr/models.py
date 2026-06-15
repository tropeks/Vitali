import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import connection, models, transaction
from django.utils import timezone
from encrypted_model_fields.fields import (
    EncryptedCharField,
    EncryptedEmailField,
    EncryptedTextField,
)

from apps.core.constants import DOSE_UNIT_CHOICES
from apps.core.fields import EncryptedJSONField


def lock_mrn_generation(year):
    """Serialize MRN generation per tenant/year on PostgreSQL."""
    if connection.vendor != "postgresql":
        return
    schema = getattr(connection, "schema_name", "public")
    lock_name = f"emr.patient.mrn.{schema}.{year}"
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [lock_name])


def generate_mrn():
    """Auto-generate medical record number: PAC-YYYY-NNNNN"""
    year = timezone.now().year
    lock_mrn_generation(year)
    last = (
        Patient.objects.filter(medical_record_number__startswith=f"PAC-{year}-")
        .order_by("-medical_record_number")
        .first()
    )
    if last:
        try:
            seq = int(last.medical_record_number.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"PAC-{year}-{seq:05d}"


class Patient(models.Model):
    GENDER_CHOICES = [
        ("M", "Masculino"),
        ("F", "Feminino"),
        ("O", "Outro"),
        ("N", "Não informado"),
    ]
    BLOOD_TYPE_CHOICES = [
        ("A+", "A+"),
        ("A-", "A-"),
        ("B+", "B+"),
        ("B-", "B-"),
        ("AB+", "AB+"),
        ("AB-", "AB-"),
        ("O+", "O+"),
        ("O-", "O-"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    medical_record_number = models.CharField(max_length=20, unique=True, blank=True)
    # PII encrypted at rest (LGPD). Encrypted fields are stored as opaque
    # ciphertext, so they cannot be DB-indexed, ordered or filtered with
    # SQL — name search/ordering is handled in Python (see filters.py / views.py).
    full_name = EncryptedCharField(max_length=200)
    social_name = EncryptedCharField(max_length=200, blank=True)
    cpf = EncryptedCharField(max_length=14)
    birth_date = models.DateField()
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES)
    blood_type = models.CharField(max_length=5, choices=BLOOD_TYPE_CHOICES, blank=True)
    phone = EncryptedCharField(max_length=20, blank=True)
    # whatsapp stays plaintext on purpose: it is the indexed routing/dedup key
    # for the WhatsApp messaging subsystem (has_whatsapp filter, contact mapping).
    whatsapp = models.CharField(max_length=20, blank=True, db_index=True)
    email = EncryptedEmailField(blank=True)
    address = EncryptedJSONField(default=dict, blank=True)
    insurance_data = models.JSONField(default=dict, blank=True)
    emergency_contact = models.JSONField(default=dict, blank=True)
    photo_url = models.URLField(blank=True)
    notes = EncryptedTextField(blank=True)
    # NEWS2 SpO2 Scale 2 (alvo 88–92%, ex. DPOC/insuf. respiratória hipercápnica
    # crônica). Safe-by-default OFF → todos usam a Escala 1; só uma decisão clínica
    # explícita habilita a Escala 2, pois aplicá-la por engano mascara hipóxia.
    use_spo2_scale_2 = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="patients_created",
    )

    class Meta:
        # full_name is encrypted and cannot be ordered/indexed at the DB level;
        # the medical record number is sequential and gives a stable default order.
        ordering = ["medical_record_number"]
        indexes = [
            models.Index(fields=["medical_record_number"]),
            models.Index(fields=["whatsapp"]),
            models.Index(fields=["is_active", "medical_record_number"]),
        ]

    def save(self, *args, **kwargs):
        if not self.medical_record_number:
            with transaction.atomic():
                self.medical_record_number = generate_mrn()
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.medical_record_number})"

    @property
    def age(self):
        today = timezone.now().date()
        b = self.birth_date
        return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


class Allergy(models.Model):
    SEVERITY_CHOICES = [
        ("mild", "Leve"),
        ("moderate", "Moderada"),
        ("severe", "Grave"),
        ("life_threatening", "Risco de vida"),
    ]
    STATUS_CHOICES = [
        ("active", "Ativa"),
        ("inactive", "Inativa"),
        ("resolved", "Resolvida"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="allergies")
    substance = models.CharField(max_length=200)
    reaction = models.CharField(max_length=500, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    confirmed_by = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-severity", "substance"]
        verbose_name_plural = "allergies"

    def __str__(self):
        return f"{self.substance} ({self.get_severity_display()})"


class MedicalHistory(models.Model):
    TYPE_CHOICES = [
        ("chronic", "Crônica"),
        ("acute", "Aguda"),
        ("surgical", "Cirúrgica"),
        ("family", "Familiar"),
    ]
    STATUS_CHOICES = [
        ("active", "Ativa"),
        ("controlled", "Controlada"),
        ("resolved", "Resolvida"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="medical_history")
    condition = models.CharField(max_length=300)
    cid10_code = models.CharField(max_length=10, blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    onset_date = models.DateField(null=True, blank=True)
    notes = EncryptedTextField(blank=True)  # free-text clinical notes (LGPD)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["condition"]
        verbose_name_plural = "medical histories"

    def __str__(self):
        return f"{self.condition} ({self.cid10_code or 'sem CID'})"


class Professional(models.Model):
    COUNCIL_CHOICES = [
        ("CRM", "CRM"),
        ("COREN", "COREN"),
        ("CRF", "CRF"),
        ("CRO", "CRO"),
        ("CREFITO", "CREFITO"),
        ("CRP", "CRP"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField("core.User", on_delete=models.CASCADE, related_name="professional")
    council_type = models.CharField(max_length=10, choices=COUNCIL_CHOICES)
    council_number = models.CharField(max_length=20)
    council_state = models.CharField(max_length=2)
    specialty = models.CharField(max_length=100, blank=True)
    cbo_code = models.CharField(max_length=10, blank=True)
    cnes_code = models.CharField(max_length=10, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["council_type", "council_number", "council_state"]]

    def __str__(self):
        return f"{self.user.full_name} - {self.council_type} {self.council_number}/{self.council_state}"


class ScheduleConfig(models.Model):
    professional = models.OneToOneField(
        Professional, on_delete=models.CASCADE, related_name="schedule_config"
    )
    slot_duration_minutes = models.IntegerField(default=30)
    working_days = models.JSONField(default=list)
    working_hours_start = models.TimeField(default="08:00")
    working_hours_end = models.TimeField(default="18:00")
    lunch_start = models.TimeField(null=True, blank=True)
    lunch_end = models.TimeField(null=True, blank=True)
    max_simultaneous = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Agenda de {self.professional}"


class Appointment(models.Model):
    STATUS_CHOICES = [
        ("scheduled", "Agendado"),
        ("confirmed", "Confirmado"),
        ("waiting", "Aguardando"),
        ("in_progress", "Em atendimento"),
        ("completed", "Concluído"),
        ("cancelled", "Cancelado"),
        ("no_show", "Não compareceu"),
    ]
    TYPE_CHOICES = [
        ("consultation", "Consulta"),
        ("return", "Retorno"),
        ("exam", "Exame"),
        ("procedure", "Procedimento"),
        ("telemedicine", "Telemedicina"),
    ]
    SOURCE_CHOICES = [
        ("receptionist", "Recepcionista"),
        ("whatsapp", "WhatsApp"),
        ("web", "Portal Web"),
        ("phone", "Telefone"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="appointments")
    professional = models.ForeignKey(
        Professional, on_delete=models.CASCADE, related_name="appointments"
    )
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="consultation")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="scheduled")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="receptionist")
    notes = models.TextField(blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    whatsapp_reminder_sent = models.BooleanField(default=False)
    whatsapp_confirmed = models.BooleanField(default=False)
    satisfaction_rating = models.IntegerField(
        null=True, blank=True
    )  # 1=Muito bom 2=Ok 3=Poderia melhorar
    cancelled_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_appointments",
    )
    cancellation_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_appointments",
    )

    class Meta:
        ordering = ["start_time"]
        unique_together = [["professional", "start_time"]]
        indexes = [
            models.Index(fields=["professional", "start_time"]),
            models.Index(fields=["patient", "start_time"]),
            models.Index(fields=["status", "start_time"]),
            models.Index(fields=["start_time", "end_time"]),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.end_time and self.start_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "Horário de fim deve ser após o início."})
        overlapping = Appointment.objects.filter(
            professional=self.professional,
            status__in=["scheduled", "confirmed", "waiting", "in_progress"],
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        ).exclude(pk=self.pk)
        if overlapping.exists():
            raise ValidationError({"start_time": "TIME_SLOT_UNAVAILABLE"})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.patient} com {self.professional} em {self.start_time}"


# ─── Sprint 4: EMR Core ───────────────────────────────────────────────────────


class Encounter(models.Model):
    """Consulta clínica — ponto central do EMR"""

    STATUS_CHOICES = [
        ("open", "Em Aberto"),
        ("signed", "Assinada"),
        ("cancelled", "Cancelada"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="encounters")
    professional = models.ForeignKey(
        Professional, on_delete=models.PROTECT, related_name="encounters"
    )
    appointment = models.OneToOneField(
        Appointment, null=True, blank=True, on_delete=models.SET_NULL, related_name="encounter"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    encounter_date = models.DateTimeField(default=timezone.now)
    chief_complaint = EncryptedTextField(blank=True)  # free-text clinical (LGPD)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signed_encounters",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-encounter_date"]
        indexes = [
            models.Index(fields=["patient", "encounter_date"]),
            models.Index(fields=["professional", "encounter_date"]),
            models.Index(fields=["status", "encounter_date"]),
        ]

    def __str__(self):
        return f"Consulta {self.patient} — {self.encounter_date:%d/%m/%Y %H:%M}"


class SOAPNote(models.Model):
    """Nota SOAP vinculada a uma consulta"""

    encounter = models.OneToOneField(Encounter, on_delete=models.CASCADE, related_name="soap_note")
    # SOAP narrative — sensitive clinical free-text, encrypted at rest (LGPD).
    subjective = EncryptedTextField(blank=True, help_text="Queixa do paciente, história atual")
    objective = EncryptedTextField(blank=True, help_text="Exame físico, sinais vitais, achados")
    assessment = EncryptedTextField(blank=True, help_text="Diagnóstico, CID-10, impressão clínica")
    plan = EncryptedTextField(blank=True, help_text="Conduta, prescrição, retorno")
    cid10_codes = models.JSONField(default=list, help_text="Lista de códigos CID-10")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"SOAP — {self.encounter}"


class VitalSigns(models.Model):
    """Sinais vitais do encontro.

    Série temporal: um Encounter pode ter múltiplas leituras (FK, não OneToOne).
    A enfermaria mede vitais a cada 4–8h; cada leitura é uma linha imutável
    (``recorded_at`` auto). Os 3 últimos campos completam os 7 parâmetros do
    NEWS2 (deterioration wedge) — todos nullable, registrados pela enfermagem.
    """

    # ACVPU — nível de consciência do NEWS2 (Alert / Confusion / Voice / Pain /
    # Unresponsive). "C" (nova confusão) e abaixo pontuam 3 no escore.
    CONSCIOUSNESS_CHOICES = [
        ("A", "Alerta"),
        ("C", "Confusão (nova)"),
        ("V", "Resposta à voz"),
        ("P", "Resposta à dor"),
        ("U", "Não responsivo"),
    ]

    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name="vital_signs")
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    blood_pressure_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    blood_pressure_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    heart_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature_celsius = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    oxygen_saturation = models.PositiveSmallIntegerField(null=True, blank=True)
    # NEWS2 parameters (deterioration wedge) — nullable; o motor é inerte se faltar algum.
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    on_supplemental_oxygen = models.BooleanField(null=True, blank=True)
    # null=True is deliberate: NULL = "não avaliado" (param ausente → NEWS2 inerte),
    # semanticamente distinto de "" — por isso suprimimos DJ001 aqui.
    consciousness = models.CharField(  # noqa: DJ001
        max_length=1, choices=CONSCIOUSNESS_CHOICES, null=True, blank=True
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Leitura mais recente primeiro — o último snapshot dirige a tela de
        # detalhe do encontro e o escore NEWS2.
        ordering = ["-recorded_at"]

    @property
    def bmi(self):
        if self.weight_kg and self.height_cm:
            h = float(self.height_cm) / 100
            return round(float(self.weight_kg) / (h * h), 1)
        return None

    def __str__(self):
        return f"Sinais Vitais — {self.encounter}"


class ClinicalDocument(models.Model):
    """Documento clínico assinado — atestado, receita, encaminhamento"""

    DOC_TYPES = [
        ("certificate", "Atestado Médico"),
        ("prescription", "Receita"),
        ("referral", "Encaminhamento"),
        ("exam_request", "Solicitação de Exame"),
        ("report", "Laudo"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=20, choices=DOC_TYPES)
    content = EncryptedTextField()  # signed clinical document body (LGPD)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signed_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def sign(self, user):
        self.signed_at = timezone.now()
        self.signed_by = user
        self.save(update_fields=["signed_at", "signed_by"])

    @property
    def is_signed(self):
        return self.signed_at is not None

    def __str__(self):
        return f"{self.get_doc_type_display()} — {self.encounter}"


# ─── Sprint 7 (minimal S-015): Prescription ──────────────────────────────────


class Prescription(models.Model):
    """
    Receita médica — vinculada a um Encounter.
    Precisa ser assinada (signed_at não nulo) antes de poder ser dispensada.
    """

    STATUS_CHOICES = [
        ("draft", "Rascunho"),
        ("signed", "Assinada"),
        ("partially_dispensed", "Parcialmente dispensada"),
        ("dispensed", "Dispensada"),
        ("cancelled", "Cancelada"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name="prescriptions")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="prescriptions")
    prescriber = models.ForeignKey(
        Professional, on_delete=models.PROTECT, related_name="prescriptions"
    )
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default="draft", db_index=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signed_by = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="signed_prescriptions",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["encounter", "status"]),
        ]

    @property
    def is_signed(self):
        return self.signed_at is not None

    def sign(self, user):
        self.signed_at = timezone.now()
        self.signed_by = user
        self.status = "signed"
        self.save(update_fields=["signed_at", "signed_by", "status"])

    def __str__(self):
        return f"Receita {self.id} — {self.patient} ({self.get_status_display()})"


class PrescriptionItem(models.Model):
    """Item de receita — um medicamento por linha."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    # String FK to avoid circular import — pharmacy 0001 must run before emr 0005
    drug = models.ForeignKey(
        "pharmacy.Drug", on_delete=models.PROTECT, related_name="prescription_items"
    )
    generic_name = models.CharField(max_length=300, blank=True)
    quantity = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    unit_of_measure = models.CharField(max_length=20, default="un")
    dosage_instructions = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # ─── Dose-safety wedge PR A: structured dose fields ───────────────────────
    # All nullable/blank: existing rows and non-formulary drugs are unaffected.
    # These feed the deterministic dose engine in PR B; we do NOT parse free
    # text (dosage_instructions stays untouched).
    # dose_unit uses the shared apps.core.constants.DOSE_UNIT_CHOICES (mass units
    # only) so it can never silently mismatch the formulary/rule units.
    ROUTE_CHOICES = [
        ("IV", "Intravenosa"),
        ("IM", "Intramuscular"),
        ("SC", "Subcutânea"),
        ("PO", "Oral"),
    ]

    dose_amount = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=(
            "Structured dose per single administration (for dose engine, PR B). "
            "4 decimal places so sub-milligram/mcg microdoses don't truncate to 0."
        ),
    )
    dose_unit = models.CharField(max_length=10, blank=True, choices=DOSE_UNIT_CHOICES)
    route = models.CharField(max_length=4, blank=True, choices=ROUTE_CHOICES)
    frequency_per_day = models.SmallIntegerField(
        null=True,
        blank=True,
        help_text="Number of doses per day (for max-daily checks in PR B).",
    )
    # ─── Dose-engine v2 (AXIS 2): loading vs maintenance ──────────────────────
    # blank default "" → most orders are maintenance/unspecified. The dose engine
    # treats blank as "maintenance" (the safe clinical default): a loading rule is
    # selected ONLY when the prescriber explicitly marks the item as loading, so an
    # unmarked loading-magnitude dose is screened against the lower maintenance band.
    DOSE_ROLE_CHOICES = [
        ("maintenance", "Manutenção"),
        ("loading", "Ataque/Loading"),
    ]
    dose_role = models.CharField(
        max_length=12,
        blank=True,
        default="",
        choices=DOSE_ROLE_CHOICES,
        help_text=(
            "Optional dose role for the dose engine: 'loading' selects an explicit loading rule; "
            "blank/'maintenance' uses the maintenance band (safe default)."
        ),
    )

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if not self.generic_name and self.drug_id:
            from apps.pharmacy.models import Drug

            try:
                self.generic_name = Drug.objects.get(pk=self.drug_id).generic_name
            except Drug.DoesNotExist:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.drug} × {self.quantity} {self.unit_of_measure}"


# ─── Sprint 6: Insurance Cards ────────────────────────────────────────────────


class PatientInsurance(models.Model):
    """
    Patient's health insurance (convênio) card data. Per-tenant.

    provider_ans_code is a plain CharField (not FK to apps.billing.InsuranceProvider)
    to keep apps.emr free of any dependency on apps.billing.
    card_number is encrypted at rest (LGPD — PII).
    """

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="insurance_cards")
    provider_ans_code = models.CharField(max_length=20)  # código ANS da operadora
    provider_name = models.CharField(max_length=200)  # denormalised for display
    card_number = EncryptedCharField(max_length=50)  # carteirinha (LGPD)
    valid_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_active", "-created_at"]
        verbose_name = "Convênio do Paciente"
        verbose_name_plural = "Convênios dos Pacientes"

    def __str__(self):
        return f"{self.provider_name} — {self.patient}"


# ─── S-063: AI Prescription Safety Alert ─────────────────────────────────────


class AISafetyAlert(models.Model):
    """
    Tracks AI-generated drug safety alerts per prescription item.
    Created by the check_prescription_safety Celery task after LLM analysis.

    unique_together on (prescription_item, alert_type, source) prevents duplicate
    alerts if a check retries (idempotency).

    The `source` field decouples the deterministic engine's verdict row from the
    LLM explainer row. PR B's deterministic DoseChecker writes alert_type="dose"
    with source="engine"; the existing LLM checker writes source="llm". Without
    this split, a re-check via update_or_create() keyed on
    (prescription_item, alert_type) would CLOBBER a previously acknowledged /
    overridden alert (wiping override_reason / acknowledged_at). source="llm" is
    the default for backward-compatibility with existing rows.
    """

    ALERT_TYPE_CHOICES = [
        ("drug_interaction", "Interação medicamentosa"),
        ("allergy", "Alergia cruzada"),
        ("dose", "Dose fora do intervalo"),
        ("contraindication", "Contraindicação"),
    ]

    class Source(models.TextChoices):
        LLM = "llm", "LLM (explicação)"
        ENGINE = "engine", "Motor determinístico"

    SEVERITY_CHOICES = [
        ("caution", "Cautela"),
        ("contraindication", "Contraindicação"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pendente"),
        ("safe", "Seguro"),
        ("flagged", "Alertado"),
        ("acknowledged", "Reconhecido"),
        ("error", "Erro"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prescription_item = models.ForeignKey(
        PrescriptionItem, on_delete=models.CASCADE, related_name="safety_alerts"
    )
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPE_CHOICES)
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        default=Source.LLM,
        help_text="Which checker produced this row: 'llm' explainer or 'engine' verdict.",
    )
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    message = models.TextField()
    recommendation = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="flagged")
    acknowledged_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_safety_alerts",
    )
    override_reason = models.TextField(blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("prescription_item", "alert_type", "source")]
        verbose_name = "AI Safety Alert"
        verbose_name_plural = "AI Safety Alerts"

    def __str__(self):
        return f"{self.get_severity_display()} — {self.get_alert_type_display()} ({self.prescription_item})"

    def acknowledge(self, user, reason=""):
        from django.utils import timezone

        self.acknowledged_by = user
        self.override_reason = reason
        self.acknowledged_at = timezone.now()
        self.status = "acknowledged"
        self.save(update_fields=["acknowledged_by", "override_reason", "acknowledged_at", "status"])


# ─── Clinical-deterioration wedge (PR D2): NEWS2 early-warning alert ──────────


class DeteriorationAlert(models.Model):
    """Veredito do motor NEWS2 (clinical-deterioration wedge, PR D2). Per-tenant.

    Mirror do ``AISafetyAlert`` / ``pharmacy.StockAlert``: linha persistente do
    veredito do motor determinístico (``source="engine"``), com campos de ack
    para que um reconhecimento clínico permaneça, e o flywheel ``AuditLog`` em
    volta. O motor (``apps.emr.services.news2``) DECIDE; o serviço persiste.

    POSTURA — ADVISE/ESCALONAMENTO, NUNCA BLOQUEIA. O registro de sinais vitais
    jamais é bloqueado; este alerta é levantado quando o NEWS2 cruza a banda de
    risco, para o painel de deterioração e o time clínico agirem (D3).

    De-dup (LOCKED no eng-review): no máximo UM alerta ``open`` por encounter
    (UniqueConstraint parcial). Uma nova leitura ATUALIZA o alerta aberto se o
    escore SUBIU; depois do ack/resolução, uma nova leitura que volte a cruzar a
    banda cria um alerta NOVO — o histórico de escalonamentos vira trilha.
    """

    class Band(models.TextChoices):
        LOW = "low", "Baixo"
        LOW_MEDIUM = "low_medium", "Baixo-médio (escore 3 em parâmetro único)"
        MEDIUM = "medium", "Médio"
        HIGH = "high", "Alto"

    class Severity(models.TextChoices):
        ADVISE = "advise", "Avisa"
        ESCALATION = "escalation", "Escalonamento (emergência)"

    class Source(models.TextChoices):
        ENGINE = "engine", "Motor determinístico"
        # Reservado: um futuro priorizador/explicador LLM escreveria source="llm".
        LLM = "llm", "LLM (explicação)"

    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        ACKNOWLEDGED = "acknowledged", "Reconhecido"
        RESOLVED = "resolved", "Resolvido"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="deterioration_alerts"
    )
    # A leitura que disparou/atualizou o alerta (a mais recente que cruzou a banda).
    vital_signs = models.ForeignKey(
        VitalSigns, on_delete=models.CASCADE, related_name="deterioration_alerts"
    )
    score = models.PositiveSmallIntegerField()
    band = models.CharField(max_length=12, choices=Band.choices)
    # Sub-escore por parâmetro (o "porquê" do escore) — espelha NEWS2Result.breakdown.
    breakdown = models.JSONField(default=dict)
    any_param_three = models.BooleanField(default=False)
    spo2_scale = models.PositiveSmallIntegerField(help_text="Escala SpO2 aplicada (1 ou 2).")
    severity = models.CharField(max_length=12, choices=Severity.choices)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.ENGINE)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.OPEN)
    engine_version = models.CharField(max_length=40)
    message = models.TextField("Mensagem (pt-BR)")
    acknowledged_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_deterioration_alerts",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Alerta de Deterioração (NEWS2)"
        verbose_name_plural = "Alertas de Deterioração (NEWS2)"
        ordering = ["-created_at"]
        constraints = [
            # No máximo UM alerta aberto por encounter (índice único parcial). Uma
            # nova leitura faz update do alerta aberto; depois do ack/resolução o
            # parcial libera, então uma re-deterioração cria um alerta novo.
            models.UniqueConstraint(
                fields=["encounter"],
                condition=models.Q(status="open"),
                name="uniq_open_deterioration_alert_per_encounter",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "band"]),
        ]

    def __str__(self):
        return f"NEWS2 {self.score} ({self.get_band_display()}) — {self.encounter}"

    def acknowledge(self, user, note=""):
        self.acknowledged_by = user
        self.note = note
        self.acknowledged_at = timezone.now()
        self.status = self.Status.ACKNOWLEDGED
        self.save(
            update_fields=["acknowledged_by", "note", "acknowledged_at", "status", "updated_at"]
        )


# ─── S30-03: Escalation routing config (per-tenant) ──────────────────────────


class EscalationConfig(models.Model):
    """Per-tenant operator config for escalation-severity deterioration alerts.

    Controls who is notified when a DeteriorationAlert of severity ESCALATION
    is raised. NEVER blocks clinical flow — the router is always fail-safe.
    One active config per tenant is the expected usage; service reads .first().
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    is_active = models.BooleanField(default=True)
    notify_emails = models.JSONField(
        default=list,
        help_text="Lista de e-mails notificados em escalamentos (formato JSON).",
    )
    notify_role = models.CharField(
        max_length=50,
        blank=True,
        help_text="Chave de papel opcional (ex: 'nurse_coordinator') resolvida em runtime.",
    )
    min_severity = models.CharField(
        max_length=12,
        choices=DeteriorationAlert.Severity.choices,
        default=DeteriorationAlert.Severity.ESCALATION,
        help_text="Severidade mínima para acionar o roteamento.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração de escalonamento"
        verbose_name_plural = "Configurações de escalonamento"

    def __str__(self):
        status = "ativa" if self.is_active else "inativa"
        return f"EscalationConfig ({status}, {len(self.notify_emails)} e-mail(s))"


# ─── S-064: AI CID-10 Suggestion ─────────────────────────────────────────────


class AICIDSuggestion(models.Model):
    """
    Tracks CID-10 AI suggestions and acceptance outcomes.
    Used for accuracy reporting and model performance monitoring.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(
        Encounter, on_delete=models.CASCADE, related_name="cid10_suggestions"
    )
    query_text = models.TextField()
    suggestions = models.JSONField(default=list, help_text="[{code, description, confidence}, ...]")
    accepted_code = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AI CID-10 Suggestion"
        verbose_name_plural = "AI CID-10 Suggestions"

    def __str__(self):
        return f"CID10Suggest({self.encounter_id}, accepted={self.accepted_code or 'none'})"


# ─── F-03: Encounter Procedures (auto-TISS PR1) ──────────────────────────────


class EncounterProcedure(models.Model):
    """
    Procedimento (TUSS) capturado durante uma consulta clínica. Per-tenant.

    Esta é a captura clínica do procedimento — NÃO a verdade de faturamento.
    O preço é resolvido no momento de construção da guia (apps.billing, F-03 PR2),
    por isso apps.emr nunca importa apps.billing. unit_value aqui é apenas uma
    dica de UX em cache e fica nulo no PR1.

    tuss_code aponta para core.TUSSCode (schema público/compartilhado): o
    PostgreSQL não garante integridade referencial entre schemas, então a
    proteção é apenas de camada de aplicação — o signal pre_delete
    protect_tuss_code_deletion (ver apps/core/signals.py) bloqueia a exclusão.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    encounter = models.ForeignKey(Encounter, on_delete=models.CASCADE, related_name="procedures")
    # FK to PUBLIC-schema TUSSCode from a TENANT-schema model. PROTECT is unusable
    # here: Django's deletion Collector runs in the public schema and would query
    # public.emr_encounterprocedure (which does not exist) → ProgrammingError 500
    # BEFORE the pre_delete signal can raise a graceful ProtectedError. We use
    # DO_NOTHING and rely on the protect_tuss_code_deletion pre_delete signal
    # (apps/core/signals.py), which iterates tenant schemas and blocks deletion.
    # NOTE: billing's TISSGuideItem.tuss_code / PriceTableItem.tuss_code still use
    # native PROTECT and likely share this latent cross-schema crash — tracked as a
    # separate pre-existing follow-up (see docs/plans/F03-AUTO-TISS.md), NOT in this PR.
    tuss_code = models.ForeignKey(
        "core.TUSSCode", on_delete=models.DO_NOTHING, related_name="encounter_procedures"
    )
    quantity = models.DecimalField(
        "Quantidade",
        max_digits=8,
        decimal_places=2,
        default=1,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    performed_by = models.ForeignKey(
        Professional,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    # CACHED UX HINT ONLY; NOT billing truth. Resolved at guide-build time in PR2
    # (apps.billing). Left null in PR1.
    unit_value = models.DecimalField(
        "Valor unitário (R$)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField("Observações", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Procedimento da Consulta"
        verbose_name_plural = "Procedimentos da Consulta"

    def __str__(self):
        return f"{self.tuss_code_id} × {self.quantity} — {self.encounter_id}"


# ─── S-066: Appointment Cancellation Waitlist ─────────────────────────────────


class WaitlistEntry(models.Model):
    """
    Patient waiting for a cancellation slot with a specific professional.

    Lifecycle: waiting → notified → booked (or expired/cancelled).
    On cancellation, notify_next_waitlist_entry task picks the first matching entry.
    Patient has 30 min (WAITLIST_TIMEOUT_MINUTES) to respond SIM before it expires
    and the next entry is notified.
    """

    STATUS_CHOICES = [
        ("waiting", "Aguardando"),
        ("notified", "Notificado"),
        ("booked", "Agendado"),
        ("expired", "Expirado"),
        ("cancelled", "Cancelado"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="waitlist_entries")
    professional = models.ForeignKey(
        Professional, on_delete=models.CASCADE, related_name="waitlist_entries"
    )
    preferred_date_from = models.DateField()
    preferred_date_to = models.DateField()
    preferred_time_start = models.TimeField(null=True, blank=True)
    preferred_time_end = models.TimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="waiting", db_index=True
    )
    notified_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    # Slot offered during notification (for booking confirmation)
    offered_slot = models.JSONField(
        null=True, blank=True, help_text='{"start": "ISO", "end": "ISO"}'
    )
    # Task ID for the expiry task (for idempotency check)
    expiry_task_id = models.CharField(max_length=100, blank=True)
    priority = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["priority", "created_at"]
        verbose_name = "Waitlist Entry"
        verbose_name_plural = "Waitlist Entries"
        indexes = [
            models.Index(fields=["professional", "status", "priority", "created_at"]),
            models.Index(fields=["patient", "status"]),
        ]

    def __str__(self):
        return f"WaitlistEntry({self.patient}, {self.professional}, {self.get_status_display()})"


# ─── No-show prediction wedge PR N1: persistent risk row ──────────────────────


class NoShowRisk(models.Model):
    """Verdict do motor determinístico de risco de falta (no-show wedge N1).

    Mirror do ``pharmacy.StockAlert``: linha persistente do veredito (uma por
    agendamento, ``update_or_create`` keyed em ``appointment``), com ``breakdown``
    explicável e campos de flywheel. NÃO é cache efêmero — é a linha que a
    superfície (N3) e o grading (N2) consomem.

    POSTURA — ADVISE/OPERACIONAL, NUNCA BLOQUEIA agendamento ou check-in. Só
    surface a ``suggested_action``; v1 não dispara WhatsApp nem oferta de waitlist.
    Risco DERIVADO do histórico do paciente (não inventado); inerte (sem linha) se
    o paciente tem < 5 agendamentos terminais.
    """

    class Band(models.TextChoices):
        LOW = "low", "Baixo"
        MEDIUM = "medium", "Médio"
        HIGH = "high", "Alto"

    class SuggestedAction(models.TextChoices):
        NONE = "none", "Nenhuma"
        CONFIRM_ACTIVE = "confirm_active", "Confirmar ativamente"

    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        ACKNOWLEDGED = "acknowledged", "Reconhecido"
        RESOLVED = "resolved", "Resolvido"

    class Outcome(models.TextChoices):
        """Rótulo do flywheel (gradado após o ``start_time`` passar).

        médio+alto = predito-positivo, baixo = predito-negativo; agendamentos
        ``cancelled`` ficam fora da gradação (``pending``).
        """

        PENDING = "pending", "Pendente"
        TRUE_POSITIVE = "true_positive", "Acerto (faltou, previsto)"
        FALSE_POSITIVE = "false_positive", "Falso-positivo (compareceu, previsto falta)"
        FALSE_NEGATIVE = "false_negative", "Falso-negativo (faltou, não previsto)"
        TRUE_NEGATIVE = "true_negative", "Acerto (compareceu, previsto baixo)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(
        Appointment, on_delete=models.CASCADE, related_name="no_show_risk"
    )
    score = models.DecimalField(max_digits=5, decimal_places=4)
    band = models.CharField(max_length=10, choices=Band.choices, db_index=True)
    breakdown = models.JSONField(default=list)
    suggested_action = models.CharField(
        max_length=20, choices=SuggestedAction.choices, default=SuggestedAction.NONE
    )
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.OPEN)
    outcome = models.CharField(
        max_length=16, choices=Outcome.choices, default=Outcome.PENDING, db_index=True
    )
    engine_version = models.CharField(max_length=40)
    acknowledged_by = models.ForeignKey(
        "core.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_no_show_risks",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    computed_at = models.DateTimeField(auto_now=True)
    graded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Risco de Falta (motor)"
        verbose_name_plural = "Riscos de Falta (motor)"
        ordering = ["-score", "-created_at"]
        indexes = [
            models.Index(fields=["band", "outcome"]),
        ]

    def __str__(self):
        return f"NoShowRisk({self.appointment_id}, {self.get_band_display()}, {self.score})"

    def acknowledge(self, user, note=""):
        self.acknowledged_by = user
        self.note = note
        self.acknowledged_at = timezone.now()
        self.status = self.Status.ACKNOWLEDGED
        self.save(update_fields=["acknowledged_by", "note", "acknowledged_at", "status"])
