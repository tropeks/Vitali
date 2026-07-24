"""Configurable clinical form templates (anamnesis/intake) — Sprint E4.

``ClinicalFormTemplate`` describes a form as a versioned JSON schema (field
key/label/type/required/options). Templates are immutable once published —
any content change requires a new version (mirrors ``ai.AIPromptTemplate``'s
name+version pattern and ``emr.Appointment``'s ``clean()``/``full_clean()``
save-time validation idiom).

``ClinicalFormResponse`` stores a filled-in form linked to an ``Encounter``/
``Patient``. Its ``answers`` are PHI and are encrypted at rest via
``EncryptedJSONField`` (same approach as ``NursingAssessment.content``), and
are validated against the owning template's schema before save — required
fields present, declared types respected, enum values within ``options``,
and no undeclared keys accepted.
"""

import uuid
from datetime import date

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.fields import EncryptedJSONField

from .models import Encounter, Patient

# Field types a template schema entry may declare.
FIELD_TYPES = (
    "text",
    "textarea",
    "number",
    "boolean",
    "date",
    "select",
    "radio",
    "multiselect",
)
# Types that require a non-empty ``options`` list of strings.
OPTION_FIELD_TYPES = ("select", "radio", "multiselect")

# Immutable once published: changing any of these on a published template
# must go through ``new_version`` instead of an in-place edit.
_FROZEN_ON_PUBLISH = ("name", "specialty", "version", "schema")


def validate_form_schema(schema):
    """Validate a template's field schema structure.

    ``schema`` must be a non-empty list of field descriptors:
    ``{"key": str, "label": str, "type": one of FIELD_TYPES,
    "required": bool (optional, default False),
    "options": list[str] (required for select/radio/multiselect)}``.
    Raises ``django.core.exceptions.ValidationError`` on any violation.
    """
    if not isinstance(schema, list) or not schema:
        raise ValidationError({"schema": "schema deve ser uma lista não vazia de campos."})
    seen_keys = set()
    for field in schema:
        if not isinstance(field, dict):
            raise ValidationError({"schema": "cada campo do schema deve ser um objeto."})
        key = field.get("key")
        if not key or not isinstance(key, str):
            raise ValidationError({"schema": "cada campo requer 'key' (string não vazia)."})
        if key in seen_keys:
            raise ValidationError({"schema": f"chave duplicada no schema: {key!r}."})
        seen_keys.add(key)
        label = field.get("label")
        if not label or not isinstance(label, str):
            raise ValidationError({"schema": f"campo {key!r} requer 'label' (string não vazia)."})
        ftype = field.get("type")
        if ftype not in FIELD_TYPES:
            raise ValidationError({"schema": f"campo {key!r} tem 'type' inválido: {ftype!r}."})
        if "required" in field and not isinstance(field["required"], bool):
            raise ValidationError({"schema": f"campo {key!r}: 'required' deve ser booleano."})
        if ftype in OPTION_FIELD_TYPES:
            options = field.get("options")
            if (
                not isinstance(options, list)
                or not options
                or not all(isinstance(opt, str) and opt for opt in options)
            ):
                raise ValidationError(
                    {"schema": f"campo {key!r} ({ftype}) requer 'options' (lista de strings)."}
                )


def validate_form_answers(schema, answers):
    """Validate ``answers`` against a (already-structurally-valid) ``schema``.

    Enforces: required fields present, no undeclared keys, and declared
    types/enum options respected for every key that is present. Raises
    ``django.core.exceptions.ValidationError`` on any violation.
    """
    if not isinstance(answers, dict):
        raise ValidationError({"answers": "answers deve ser um objeto (dict)."})
    fields_by_key = {field["key"]: field for field in schema}
    unknown = sorted(set(answers) - set(fields_by_key))
    if unknown:
        raise ValidationError({"answers": f"campos não declarados no schema: {unknown}."})
    for key, field in fields_by_key.items():
        required = bool(field.get("required", False))
        present = key in answers and answers[key] not in (None, "")
        if required and not present:
            raise ValidationError({"answers": f"campo obrigatório ausente: {key!r}."})
        if not present:
            continue
        value = answers[key]
        ftype = field["type"]
        if ftype in ("text", "textarea"):
            if not isinstance(value, str):
                raise ValidationError({"answers": f"campo {key!r} deve ser texto."})
        elif ftype == "number":
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValidationError({"answers": f"campo {key!r} deve ser numérico."})
        elif ftype == "boolean":
            if not isinstance(value, bool):
                raise ValidationError({"answers": f"campo {key!r} deve ser booleano."})
        elif ftype == "date":
            if not isinstance(value, str):
                raise ValidationError({"answers": f"campo {key!r} deve ser data (string ISO)."})
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise ValidationError({"answers": f"campo {key!r} tem data inválida."}) from exc
        elif ftype in ("select", "radio"):
            if value not in field["options"]:
                raise ValidationError({"answers": f"campo {key!r} tem valor fora de 'options'."})
        elif ftype == "multiselect":
            if not isinstance(value, list) or not all(v in field["options"] for v in value):
                raise ValidationError(
                    {"answers": f"campo {key!r} tem valor(es) fora de 'options'."}
                )


class ClinicalFormTemplate(models.Model):
    """Versioned, specialty-scoped clinical form (anamnesis/intake) template.

    Immutable once published: publishing freezes ``name``/``specialty``/
    ``version``/``schema``; further content changes must go through
    :meth:`new_version`, which creates a new draft row with ``version + 1``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    specialty = models.CharField(max_length=100, db_index=True)
    version = models.PositiveIntegerField(default=1)
    schema = models.JSONField(
        help_text="Lista de campos: key/label/type/required/options.",
    )
    active = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "specialty", "-version"]
        unique_together = [("name", "specialty", "version")]

    def clean(self):
        super().clean()
        validate_form_schema(self.schema)
        if self.pk:
            try:
                original = ClinicalFormTemplate.objects.get(pk=self.pk)
            except ClinicalFormTemplate.DoesNotExist:
                original = None
            if original is not None and original.is_published:
                changed = [
                    field
                    for field in _FROZEN_ON_PUBLISH
                    if getattr(original, field) != getattr(self, field)
                ]
                if changed:
                    raise ValidationError(
                        "Template publicado é imutável "
                        f"(campos alterados: {changed}); crie uma nova versão."
                    )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def publish(self):
        """Freeze this template. Idempotent-unsafe by design: publishing an
        already-published template is rejected so callers notice the no-op."""
        if self.is_published:
            raise ValidationError("Template já publicado.")
        self.is_published = True
        self.published_at = timezone.now()
        self.save()
        return self

    def new_version(self, schema=None, **overrides):
        """Create the next version of this template as an unpublished draft.

        Only published templates may be versioned forward (a draft is edited
        in place instead). ``schema`` defaults to a copy of this version's
        schema when not given.
        """
        if not self.is_published:
            raise ValidationError("Somente templates publicados podem gerar nova versão.")
        next_version = (
            ClinicalFormTemplate.objects.filter(name=self.name, specialty=self.specialty).aggregate(
                models.Max("version")
            )["version__max"]
            or self.version
        ) + 1
        return ClinicalFormTemplate.objects.create(
            name=overrides.get("name", self.name),
            specialty=overrides.get("specialty", self.specialty),
            version=next_version,
            schema=schema if schema is not None else list(self.schema),
            active=overrides.get("active", self.active),
        )

    def __str__(self):
        return f"{self.name} ({self.specialty}) v{self.version}"


class ClinicalFormResponse(models.Model):
    """A filled-in clinical form, linked to an Encounter/Patient.

    ``answers`` are PHI and encrypted at rest (same ``EncryptedJSONField``
    approach as ``NursingAssessment.content``) and are validated against
    ``template.schema`` before every save.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        ClinicalFormTemplate, on_delete=models.PROTECT, related_name="responses"
    )
    encounter = models.ForeignKey(
        Encounter, on_delete=models.PROTECT, related_name="form_responses"
    )
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="form_responses")
    answers = EncryptedJSONField(default=dict)
    filled_by = models.ForeignKey(
        "core.User", on_delete=models.PROTECT, related_name="form_responses"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["encounter", "created_at"]),
            models.Index(fields=["patient", "created_at"]),
        ]

    def clean(self):
        super().clean()
        if self.template_id:
            validate_form_answers(self.template.schema, self.answers)
        if self.encounter_id and self.patient_id and self.encounter.patient_id != self.patient_id:
            raise ValidationError(
                {"patient": "O paciente deve ser o mesmo do encontro (encounter)."}
            )

    def save(self, *args, **kwargs):
        if not self.patient_id and self.encounter_id:
            self.patient_id = self.encounter.patient_id
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.template.name} — {self.patient} ({self.created_at:%d/%m/%Y})"
