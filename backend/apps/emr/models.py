import uuid
from django.db import models
from encrypted_model_fields.fields import EncryptedCharField


def generate_mrn():
    """Auto-generate medical record number: PAC-YYYY-NNNNN"""
    from django.utils import timezone
    year = timezone.now().year
    last = Patient.objects.filter(
        medical_record_number__startswith=f'PAC-{year}-'
    ).order_by('-medical_record_number').first()
    if last:
        try:
            seq = int(last.medical_record_number.split('-')[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f'PAC-{year}-{seq:05d}'


class Patient(models.Model):
    GENDER_CHOICES = [
        ('M', 'Masculino'), ('F', 'Feminino'),
        ('O', 'Outro'), ('N', 'Não informado'),
    ]
    BLOOD_TYPE_CHOICES = [
        ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
        ('AB+', 'AB+'), ('AB-', 'AB-'), ('O+', 'O+'), ('O-', 'O-'),
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
        'core.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='patients_created'
    )

    class Meta:
        ordering = ['full_name']
        indexes = [
            models.Index(fields=['full_name']),
            models.Index(fields=['medical_record_number']),
            models.Index(fields=['whatsapp']),
            models.Index(fields=['is_active', 'full_name']),
        ]

    def save(self, *args, **kwargs):
        if not self.medical_record_number:
            self.medical_record_number = generate_mrn()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.full_name} ({self.medical_record_number})'

    @property
    def age(self):
        from django.utils import timezone
        today = timezone.now().date()
        b = self.birth_date
        return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


class Allergy(models.Model):
    SEVERITY_CHOICES = [
        ('mild', 'Leve'), ('moderate', 'Moderada'),
        ('severe', 'Grave'), ('life_threatening', 'Risco de vida'),
    ]
    STATUS_CHOICES = [
        ('active', 'Ativa'), ('inactive', 'Inativa'), ('resolved', 'Resolvida'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='allergies')
    substance = models.CharField(max_length=200)
    reaction = models.CharField(max_length=500, blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    confirmed_by = models.ForeignKey(
        'core.User', on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-severity', 'substance']
        verbose_name_plural = 'allergies'

    def __str__(self):
        return f'{self.substance} ({self.get_severity_display()})'


class MedicalHistory(models.Model):
    TYPE_CHOICES = [
        ('chronic', 'Crônica'), ('acute', 'Aguda'),
        ('surgical', 'Cirúrgica'), ('family', 'Familiar'),
    ]
    STATUS_CHOICES = [
        ('active', 'Ativa'), ('controlled', 'Controlada'), ('resolved', 'Resolvida'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='medical_history')
    condition = models.CharField(max_length=300)
    cid10_code = models.CharField(max_length=10, blank=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    onset_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['condition']
        verbose_name_plural = 'medical histories'

    def __str__(self):
        return f'{self.condition} ({self.cid10_code or "sem CID"})'


class Professional(models.Model):
    COUNCIL_CHOICES = [
        ('CRM', 'CRM'), ('COREN', 'COREN'), ('CRF', 'CRF'),
        ('CRO', 'CRO'), ('CREFITO', 'CREFITO'), ('CRP', 'CRP'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField('core.User', on_delete=models.CASCADE, related_name='professional')
    council_type = models.CharField(max_length=10, choices=COUNCIL_CHOICES)
    council_number = models.CharField(max_length=20)
    council_state = models.CharField(max_length=2)
    specialty = models.CharField(max_length=100, blank=True)
    cbo_code = models.CharField(max_length=10, blank=True)
    cnes_code = models.CharField(max_length=10, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['council_type', 'council_number', 'council_state']]

    def __str__(self):
        return f'{self.user.full_name} - {self.council_type} {self.council_number}/{self.council_state}'
