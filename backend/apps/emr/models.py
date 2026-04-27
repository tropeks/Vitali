import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField


def generate_mrn():
    """Auto-generate medical record number: PAC-YYYY-NNNNN"""
    year = timezone.now().year
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
    full_name = models.CharField(max_length=200, db_index=True)
    social_name = models.CharField(max_length=200, blank=True)
    cpf = EncryptedCharField(max_length=14)
    birth_date = models.DateField()
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES)
    blood_type = models.CharField(max_length=5, choices=BLOOD_TYPE_CHOICES, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField(max_length=20, blank=True, db_index=True)
    email = models.EmailField(blank=True)
    address = models.JSONField(default=dict, blank=True)
    insurance_data = models.JSONField(default=dict, blank=True)
    emergency_contact = models.JSONField(default=dict, blank=True)
    photo_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)
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
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["full_name"]),
            models.Index(fields=["medical_record_number"]),
            models.Index(fields=["whatsapp"]),
            models.Index(fields=["is_active", "full_name"]),
        ]

    def save(self, *args, **kwargs):
        if not self.medical_record_number:
            self.medical_record_number = generate_mrn()
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
    notes = models.TextField(blank=True)
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
    chief_complaint = models.TextField(blank=True)
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
    subjective = models.TextField(blank=True, help_text="Queixa do paciente, história atual")
    objective = models.TextField(blank=True, help_text="Exame físico, sinais vitais, achados")
    assessment = models.TextField(blank=True, help_text="Diagnóstico, CID-10, impressão clínica")
    plan = models.TextField(blank=True, help_text="Conduta, prescrição, retorno")
    cid10_codes = models.JSONField(default=list, help_text="Lista de códigos CID-10")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"SOAP — {self.encounter}"


class VitalSigns(models.Model):
    """Sinais vitais do encontro"""

    encounter = models.OneToOneField(
        Encounter, on_delete=models.CASCADE, related_name="vital_signs"
    )
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    blood_pressure_systolic = models.PositiveSmallIntegerField(null=True, blank=True)
    blood_pressure_diastolic = models.PositiveSmallIntegerField(null=True, blank=True)
    heart_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature_celsius = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    oxygen_saturation = models.PositiveSmallIntegerField(null=True, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

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
    content = models.TextField()
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

    unique_together on (prescription_item, alert_type) prevents duplicate alerts
    if the task retries (idempotency).
    """

    ALERT_TYPE_CHOICES = [
        ("drug_interaction", "Interação medicamentosa"),
        ("allergy", "Alergia cruzada"),
        ("dose", "Dose fora do intervalo"),
        ("contraindication", "Contraindicação"),
    ]
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
        unique_together = [("prescription_item", "alert_type")]
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
