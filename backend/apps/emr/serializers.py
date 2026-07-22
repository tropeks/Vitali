import re

from django.db import transaction
from rest_framework import serializers

from .models import (
    Allergy,
    Appointment,
    ClinicalDocument,
    DuplicatePatientCandidate,
    Encounter,
    EncounterProcedure,
    LabOrder,
    LabOrderItem,
    LabTest,
    MedicalHistory,
    Patient,
    PatientIdentifier,
    PatientInsurance,
    Prescription,
    PrescriptionItem,
    Professional,
    ScheduleConfig,
    SOAPNote,
    VitalSigns,
)


class PatientIdentifierSerializer(serializers.ModelSerializer):
    value = serializers.CharField(write_only=True, max_length=255)

    class Meta:
        model = PatientIdentifier
        fields = (
            "id",
            "patient",
            "system",
            "issuer",
            "value",
            "use",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        from .services_mpi import identifier_digest

        system = attrs.get("system", getattr(self.instance, "system", "")).strip().lower()
        issuer = attrs.get("issuer", getattr(self.instance, "issuer", "")).strip().lower()
        value = attrs.get("value")
        if value is None and self.instance is not None:
            value = self.instance.value
        digest = identifier_digest(system, issuer, value)
        existing = PatientIdentifier.objects.filter(
            system=system, issuer=issuer, value_digest=digest
        )
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(
                {"value": "Este identificador já está associado a um paciente."}
            )
        attrs["system"] = system
        attrs["issuer"] = issuer
        return attrs


class DuplicatePatientCandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DuplicatePatientCandidate
        fields = (
            "id",
            "patient_a",
            "patient_b",
            "score",
            "reasons",
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


def validate_cpf(cpf: str) -> str:
    cpf = re.sub(r"\D", "", cpf)
    if len(cpf) != 11 or len(set(cpf)) == 1:
        raise serializers.ValidationError("CPF inválido.")
    for i in range(2):
        total = sum(int(cpf[j]) * (10 + i - j) for j in range(9 + i))
        digit = (total * 10 % 11) % 10
        if digit != int(cpf[9 + i]):
            raise serializers.ValidationError("CPF inválido.")
    return cpf


def digits_only_identifier(value: str, *, length: int, label: str) -> str:
    """Normalize a formatted national identifier without logging its value."""
    normalized = re.sub(r"\D", "", value)
    if normalized and len(normalized) != length:
        raise serializers.ValidationError(f"{label} deve conter {length} dígitos.")
    return normalized


class AllergySerializer(serializers.ModelSerializer):
    severity_display = serializers.CharField(source="get_severity_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Allergy
        fields = [
            "id",
            "substance",
            "reaction",
            "severity",
            "severity_display",
            "status",
            "status_display",
            "confirmed_by",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class MedicalHistorySerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = MedicalHistory
        fields = [
            "id",
            "condition",
            "cid10_code",
            "type",
            "type_display",
            "status",
            "status_display",
            "onset_date",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class PatientListSerializer(serializers.ModelSerializer):
    age = serializers.IntegerField(read_only=True)
    cpf_masked = serializers.SerializerMethodField()
    active_allergies_count = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = [
            "id",
            "medical_record_number",
            "full_name",
            "social_name",
            "birth_date",
            "age",
            "gender",
            "preferred_language",
            "phone",
            "whatsapp",
            "cpf_masked",
            "is_active",
            "active_allergies_count",
            "created_at",
        ]

    def get_cpf_masked(self, obj):
        return "***.***.***-**"

    def get_active_allergies_count(self, obj):
        return obj.allergies.filter(status="active").count()


class PatientSerializer(serializers.ModelSerializer):
    age = serializers.IntegerField(read_only=True)
    cpf = serializers.CharField(write_only=True)
    cpf_masked = serializers.SerializerMethodField(read_only=True)
    cns = serializers.CharField(write_only=True, required=False, allow_blank=True)
    cns_masked = serializers.SerializerMethodField(read_only=True)
    allergies = AllergySerializer(many=True, read_only=True)
    medical_history = MedicalHistorySerializer(many=True, read_only=True)
    gender_display = serializers.CharField(source="get_gender_display", read_only=True)

    class Meta:
        model = Patient
        fields = [
            "id",
            "medical_record_number",
            "full_name",
            "social_name",
            "cpf",
            "cpf_masked",
            "cns",
            "cns_masked",
            "identity_document",
            "identity_issuer",
            "identity_state",
            "birth_date",
            "birth_city",
            "birth_state",
            "nationality",
            "age",
            "gender",
            "gender_display",
            "race_color",
            "marital_status",
            "mother_name",
            "father_name",
            "occupation",
            "education_level",
            "preferred_language",
            "blood_type",
            "phone",
            "whatsapp",
            "email",
            "address",
            "insurance_data",
            "emergency_contact",
            "accessibility_needs",
            "photo_url",
            "notes",
            "is_active",
            "allergies",
            "medical_history",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = ["id", "medical_record_number", "created_at", "updated_at", "created_by"]

    def get_cpf_masked(self, obj):
        return "***.***.***-**"

    def get_cns_masked(self, obj):
        return "*** **** **** ****" if obj.cns else ""

    def validate_cpf(self, value):
        return validate_cpf(value)

    def validate_cns(self, value):
        return digits_only_identifier(value, length=15, label="CNS")

    def validate_identity_state(self, value):
        return value.strip().upper()

    def validate_birth_state(self, value):
        return value.strip().upper()

    def validate_preferred_language(self, value):
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z]{2})?", value):
            raise serializers.ValidationError("Idioma deve usar um código BCP 47, como pt-BR.")
        language, *region = value.split("-")
        return language.lower() + (f"-{region[0].upper()}" if region else "")


class PatientCreateSerializer(PatientSerializer):
    class Meta(PatientSerializer.Meta):
        fields = [
            f
            for f in PatientSerializer.Meta.fields
            if f not in ("allergies", "medical_history", "cpf_masked")
        ]


class ProfessionalSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    council_type_display = serializers.CharField(source="get_council_type_display", read_only=True)

    class Meta:
        model = Professional
        fields = [
            "id",
            "user",
            "user_name",
            "user_email",
            "council_type",
            "council_type_display",
            "council_number",
            "council_state",
            "specialty",
            "cbo_code",
            "cnes_code",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ScheduleConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleConfig
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]


class AppointmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_mrn = serializers.CharField(source="patient.medical_record_number", read_only=True)
    professional_name = serializers.CharField(source="professional.user.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    duration_minutes = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "patient",
            "patient_name",
            "patient_mrn",
            "professional",
            "professional_name",
            "start_time",
            "end_time",
            "duration_minutes",
            "type",
            "type_display",
            "status",
            "status_display",
            "source",
            "notes",
            "whatsapp_reminder_sent",
            "whatsapp_confirmed",
            "cancellation_reason",
            "arrived_at",
            "started_at",
            "created_at",
        ]
        read_only_fields = ["id", "arrived_at", "started_at", "created_at"]

    def get_duration_minutes(self, obj):
        delta = obj.end_time - obj.start_time
        return int(delta.total_seconds() / 60)

    def validate(self, data):
        if data.get("end_time") and data.get("start_time"):
            if data["end_time"] <= data["start_time"]:
                raise serializers.ValidationError(
                    {"end_time": "Horário de fim deve ser após o início."}
                )
        return data


# ─── Sprint 4: EMR Core serializers ──────────────────────────────────────────


class VitalSignsSerializer(serializers.ModelSerializer):
    bmi = serializers.FloatField(read_only=True)
    consciousness_display = serializers.CharField(
        source="get_consciousness_display", read_only=True, default=None
    )

    class Meta:
        model = VitalSigns
        fields = [
            "id",
            "encounter",
            "weight_kg",
            "height_cm",
            "blood_pressure_systolic",
            "blood_pressure_diastolic",
            "heart_rate",
            "temperature_celsius",
            "oxygen_saturation",
            # NEWS2 parameters (deterioration wedge).
            "respiratory_rate",
            "on_supplemental_oxygen",
            "consciousness",
            "consciousness_display",
            "bmi",
            "recorded_at",
        ]
        read_only_fields = ["id", "recorded_at", "bmi"]


class SOAPNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = SOAPNote
        fields = [
            "id",
            "encounter",
            "subjective",
            "objective",
            "assessment",
            "plan",
            "cid10_codes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ClinicalDocumentSerializer(serializers.ModelSerializer):
    is_signed = serializers.BooleanField(read_only=True)
    doc_type_display = serializers.CharField(source="get_doc_type_display", read_only=True)
    signed_by_name = serializers.CharField(
        source="signed_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = ClinicalDocument
        fields = [
            "id",
            "encounter",
            "doc_type",
            "doc_type_display",
            "content",
            "is_signed",
            "signed_at",
            "signed_by",
            "signed_by_name",
            "created_at",
        ]
        read_only_fields = ["id", "signed_at", "signed_by", "created_at"]


class LabTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabTest
        fields = [
            "id",
            "code",
            "name",
            "category",
            "result_type",
            "method",
            "loinc_code",
            "specimen_type",
            "unit",
            "reference_range",
            "components",
            "reference_ranges",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_components(self, value):
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise serializers.ValidationError("Use uma lista de componentes estruturados.")
        required = {"code", "name"}
        if any(not required.issubset(item) for item in value):
            raise serializers.ValidationError("Cada componente requer code e name.")
        codes = [item["code"] for item in value]
        if len(codes) != len(set(codes)):
            raise serializers.ValidationError("Os códigos dos componentes devem ser únicos.")
        return value

    def validate_reference_ranges(self, value):
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise serializers.ValidationError("Use uma lista de faixas estruturadas.")
        allowed = {"sex", "age_min_days", "age_max_days", "lower", "upper", "unit", "text"}
        for item in value:
            if not set(item).issubset(allowed):
                raise serializers.ValidationError(
                    "Faixa de referência contém campos desconhecidos."
                )
            if not ({"lower", "upper", "text"} & set(item)):
                raise serializers.ValidationError("A faixa requer lower, upper ou text.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        result_type = attrs.get("result_type", getattr(self.instance, "result_type", None))
        components = attrs.get("components", getattr(self.instance, "components", []))
        if result_type == LabTest.ResultType.PANEL and not components:
            raise serializers.ValidationError({"components": "Painéis requerem componentes."})
        return attrs


class LabOrderItemSerializer(serializers.ModelSerializer):
    abnormal_flag_display = serializers.CharField(
        source="get_abnormal_flag_display", read_only=True
    )
    is_validated = serializers.BooleanField(read_only=True)
    validated_by_name = serializers.CharField(
        source="validated_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = LabOrderItem
        fields = [
            "id",
            "test",
            "test_name",
            "category",
            "result_type",
            "method",
            "loinc_code",
            "specimen_type",
            "unit",
            "reference_range",
            "components",
            "reference_ranges",
            "result_value",
            "result_data",
            "microbiology",
            "abnormal_flag",
            "abnormal_flag_display",
            "result_notes",
            "resulted_at",
            "validated_at",
            "validated_by",
            "validated_by_name",
            "is_validated",
        ]
        read_only_fields = [
            "id",
            "test",
            "test_name",
            "category",
            "result_type",
            "method",
            "loinc_code",
            "specimen_type",
            "unit",
            "reference_range",
            "components",
            "reference_ranges",
            "resulted_at",
            "validated_at",
            "validated_by",
        ]

    def validate_result_value(self, value):
        return value.strip()

    def validate_result_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Use um objeto de resultado estruturado.")
        return value

    def validate_microbiology(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Use um objeto de microbiologia estruturado.")
        allowed = {"organisms", "culture_result", "microscopy", "comments"}
        if not set(value).issubset(allowed):
            raise serializers.ValidationError("Microbiologia contém campos desconhecidos.")
        organisms = value.get("organisms", [])
        if not isinstance(organisms, list) or any(not isinstance(item, dict) for item in organisms):
            raise serializers.ValidationError("organisms deve ser uma lista de objetos.")
        for organism in organisms:
            if not organism.get("name"):
                raise serializers.ValidationError("Cada organismo requer name.")
            antibiogram = organism.get("antibiogram", [])
            if not isinstance(antibiogram, list) or any(
                not isinstance(entry, dict)
                or not {"antimicrobial", "interpretation"}.issubset(entry)
                for entry in antibiogram
            ):
                raise serializers.ValidationError(
                    "Antibiograma requer antimicrobial e interpretation em cada item."
                )
        return value

    def validate(self, attrs):
        result_value = attrs.get("result_value", getattr(self.instance, "result_value", ""))
        result_data = attrs.get("result_data", getattr(self.instance, "result_data", {}))
        microbiology = attrs.get("microbiology", getattr(self.instance, "microbiology", {}))
        if not (result_value and result_value.strip()) and not result_data and not microbiology:
            raise serializers.ValidationError(
                {"result_value": "Informe um resultado textual ou estruturado."}
            )
        return attrs


class LabOrderSerializer(serializers.ModelSerializer):
    test_ids = serializers.PrimaryKeyRelatedField(
        queryset=LabTest.objects.filter(active=True), many=True, write_only=True, required=False
    )
    items = LabOrderItemSerializer(many=True, read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_mrn = serializers.CharField(source="patient.medical_record_number", read_only=True)
    requested_by_name = serializers.CharField(source="requested_by.full_name", read_only=True)
    collected_by_name = serializers.CharField(
        source="collected_by.full_name", read_only=True, default=None
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = LabOrder
        fields = [
            "id",
            "patient",
            "patient_name",
            "patient_mrn",
            "encounter",
            "status",
            "status_display",
            "clinical_indication",
            "notes",
            "requested_by",
            "requested_by_name",
            "requested_at",
            "accession_number",
            "collected_at",
            "collected_by",
            "collected_by_name",
            "collection_notes",
            "specimen_details",
            "completed_at",
            "test_ids",
            "items",
        ]
        read_only_fields = [
            "id",
            "status",
            "requested_by",
            "requested_at",
            "accession_number",
            "collected_at",
            "collected_by",
            "collected_by_name",
            "collection_notes",
            "specimen_details",
            "completed_at",
        ]

    def validate(self, attrs):
        encounter = attrs.get("encounter")
        patient = attrs.get("patient")
        if encounter and patient and encounter.patient_id != patient.id:
            raise serializers.ValidationError(
                {"encounter": "O atendimento não pertence ao paciente informado."}
            )
        if self.instance is None:
            tests = attrs.get("test_ids") or []
            if not tests:
                raise serializers.ValidationError({"test_ids": "Selecione ao menos um exame."})
            test_ids = [test.pk for test in tests]
            if len(test_ids) != len(set(test_ids)):
                raise serializers.ValidationError(
                    {"test_ids": "Um mesmo exame não pode ser incluído mais de uma vez."}
                )
        elif self.instance.status in (LabOrder.Status.COMPLETED, LabOrder.Status.CANCELLED):
            raise serializers.ValidationError("Pedidos finalizados não podem ser alterados.")
        elif "patient" in attrs or "encounter" in attrs or "test_ids" in attrs:
            raise serializers.ValidationError(
                "Paciente, atendimento e exames não podem ser alterados após a solicitação."
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        tests = validated_data.pop("test_ids")
        order = LabOrder.objects.create(**validated_data)
        LabOrderItem.objects.bulk_create(
            [
                LabOrderItem(
                    order=order,
                    test=test,
                    test_name=test.name,
                    category=test.category,
                    result_type=test.result_type,
                    method=test.method,
                    loinc_code=test.loinc_code,
                    specimen_type=test.specimen_type,
                    unit=test.unit,
                    reference_range=test.reference_range,
                    components=test.components,
                    reference_ranges=test.reference_ranges,
                )
                for test in tests
            ]
        )
        return order


class EncounterListSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_mrn = serializers.CharField(source="patient.medical_record_number", read_only=True)
    professional_name = serializers.CharField(source="professional.user.full_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Encounter
        fields = [
            "id",
            "patient",
            "patient_name",
            "patient_mrn",
            "professional",
            "professional_name",
            "encounter_date",
            "status",
            "status_display",
            "chief_complaint",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class EncounterSerializer(serializers.ModelSerializer):
    patient_detail = PatientListSerializer(source="patient", read_only=True)
    professional_name = serializers.CharField(source="professional.user.full_name", read_only=True)
    professional_specialty = serializers.CharField(source="professional.specialty", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    soap_note = SOAPNoteSerializer(read_only=True)
    # VitalSigns is now a time-series (FK, many rows per encounter). The detail
    # view keeps its single-object contract by surfacing the latest reading.
    vital_signs = serializers.SerializerMethodField()
    documents = ClinicalDocumentSerializer(many=True, read_only=True)

    def get_vital_signs(self, obj):
        latest = obj.vital_signs.first()  # Meta.ordering = -recorded_at
        if latest is None:
            return None
        return VitalSignsSerializer(latest, context=self.context).data

    class Meta:
        model = Encounter
        fields = [
            "id",
            "patient",
            "patient_detail",
            "professional",
            "professional_name",
            "professional_specialty",
            "appointment",
            "encounter_date",
            "status",
            "status_display",
            "chief_complaint",
            "soap_note",
            "vital_signs",
            "documents",
            "signed_at",
            "signed_by",
            "created_at",
            "updated_at",
        ]
        # status / signed_at / signed_by are sign-managed: they may ONLY change
        # through the dedicated `sign` action (EncounterSigningService), never via
        # a generic PATCH. Leaving `status` writable would let an emr.write client
        # flip a signed encounter back to "open", mutate its procedures, and re-sign
        # it — defeating the CFM signature-integrity write-gate the whole F-03
        # feature relies on.
        read_only_fields = [
            "id",
            "status",
            "signed_at",
            "signed_by",
            "created_at",
            "updated_at",
        ]


class PatientInsuranceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientInsurance
        fields = [
            "id",
            "patient",
            "provider_ans_code",
            "provider_name",
            "card_number",
            "valid_until",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
        extra_kwargs = {
            "patient": {"read_only": True},  # set from URL, not body
        }


class EncounterProcedureSerializer(serializers.ModelSerializer):
    """
    Procedimento (TUSS) de uma consulta. tuss_code é gravável por id;
    detalhe (code/description) é somente leitura. unit_value é somente leitura
    (dica de UX em cache — preço real resolvido em F-03 PR2, em apps.billing).
    """

    tuss_code_detail = serializers.SerializerMethodField()
    performed_by_name = serializers.CharField(
        source="performed_by.user.full_name", read_only=True, default=None
    )

    class Meta:
        model = EncounterProcedure
        fields = [
            "id",
            "encounter",
            "tuss_code",
            "tuss_code_detail",
            "quantity",
            "performed_by",
            "performed_by_name",
            "unit_value",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "encounter",
            "unit_value",
            "created_at",
            "updated_at",
        ]

    def get_tuss_code_detail(self, obj):
        tc = obj.tuss_code
        return {"id": tc.id, "code": tc.code, "description": tc.description}

    def validate_quantity(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError("Quantidade deve ser maior que zero.")
        return value

    def validate(self, data):
        # Object-level so the rule holds on PATCH too: a field-level
        # validate_tuss_code() is skipped when tuss_code is absent from the
        # payload, but it must still run whenever tuss_code IS supplied (create
        # or update). PATCH of only quantity/notes (no tuss_code) is unaffected.
        tuss_code = data.get("tuss_code")
        if tuss_code is not None and not tuss_code.active:
            raise serializers.ValidationError(
                {"tuss_code": "Código TUSS inativo não pode ser usado em procedimento."}
            )
        return data


class PrescriptionItemSerializer(serializers.ModelSerializer):
    drug_name = serializers.CharField(source="drug.name", read_only=True)
    drug_generic_name = serializers.CharField(source="drug.generic_name", read_only=True)
    drug_is_controlled = serializers.BooleanField(source="drug.is_controlled", read_only=True)

    class Meta:
        model = PrescriptionItem
        fields = [
            "id",
            "prescription",
            "drug",
            "drug_name",
            "drug_generic_name",
            "drug_is_controlled",
            "generic_name",
            "quantity",
            "unit_of_measure",
            "dosage_instructions",
            "dose_amount",
            "dose_unit",
            "route",
            "frequency_per_day",
            "dose_role",
            "notes",
        ]
        # `prescription` is read-only: an item's parent is set once at creation
        # (PrescriptionItemViewSet.perform_create passes it explicitly). Leaving it
        # writable would let a PATCH re-parent a draft item onto an already-signed
        # prescription, mutating signed content past the signed-status guard.
        read_only_fields = ["id", "generic_name", "prescription"]


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_signed = serializers.BooleanField(read_only=True)
    prescriber_name = serializers.CharField(source="prescriber.user.full_name", read_only=True)
    patient_name = serializers.CharField(source="patient.full_name", read_only=True)
    patient_mrn = serializers.CharField(source="patient.medical_record_number", read_only=True)

    class Meta:
        model = Prescription
        fields = [
            "id",
            "encounter",
            "patient",
            "patient_name",
            "patient_mrn",
            "prescriber",
            "prescriber_name",
            "status",
            "status_display",
            "is_signed",
            "signed_at",
            "signed_by",
            "notes",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "patient",
            "prescriber",
            "signed_at",
            "signed_by",
            "status",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        encounter = validated_data["encounter"]
        validated_data["patient"] = encounter.patient
        validated_data["prescriber"] = encounter.professional
        return super().create(validated_data)
