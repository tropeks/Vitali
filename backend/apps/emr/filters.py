import re

import django_filters
from django.db.models import Q
from rest_framework.filters import BaseFilterBackend

from .models import Patient


def _digits(value):
    return re.sub(r"\D", "", value or "")


def _identifier(value):
    return re.sub(r"[^0-9a-z]", "", (value or "").casefold())


def _patient_encrypted_matches(queryset, term):
    """Return ids matching fields that are encrypted at rest.

    Ciphertext cannot be queried with SQL ``LIKE``. Keep this to a single pass
    over a narrow projection, regardless of how many encrypted fields participate.
    CPF/CNS/document matches are exact after normalization to avoid broad scans
    leaking whether fragments of identifiers exist. Phone fragments require at
    least four digits. Add blind indexes before using this at very large scale.
    """
    needle = term.casefold()
    digits = _digits(term)
    identifier = _identifier(term)
    phone_needle = digits if len(digits) >= 4 else ""
    return [
        p.id
        for p in queryset.only(
            "id",
            "full_name",
            "social_name",
            "cpf",
            "cns",
            "identity_document",
            "phone",
            "email",
        ).iterator(chunk_size=500)
        if (
            needle in (p.full_name or "").casefold()
            or needle in (p.social_name or "").casefold()
            or (len(digits) == 11 and digits == _digits(p.cpf))
            or (len(digits) == 15 and digits == _digits(p.cns))
            or (len(identifier) >= 5 and identifier == _identifier(p.identity_document))
            or (phone_needle and phone_needle in _digits(p.phone))
            or (len(needle) >= 3 and needle in (p.email or "").casefold())
        )
    ]


def _patient_name_matches(queryset, term):
    """Compatibility helper for the explicit ``?name=`` filter."""
    needle = term.casefold()
    return [
        p.id
        for p in queryset.only("id", "full_name", "social_name").iterator(chunk_size=500)
        if needle in (p.full_name or "").casefold() or needle in (p.social_name or "").casefold()
    ]


class PatientFilter(django_filters.FilterSet):
    # full_name is encrypted → cannot use lookup_expr="icontains" (SQL LIKE on
    # ciphertext never matches). Filter in Python instead.
    name = django_filters.CharFilter(method="filter_name")
    mrn = django_filters.CharFilter(field_name="medical_record_number", lookup_expr="icontains")
    gender = django_filters.ChoiceFilter(choices=Patient.GENDER_CHOICES)
    birth_date_from = django_filters.DateFilter(field_name="birth_date", lookup_expr="gte")
    birth_date_to = django_filters.DateFilter(field_name="birth_date", lookup_expr="lte")
    has_whatsapp = django_filters.BooleanFilter(method="filter_has_whatsapp")

    class Meta:
        model = Patient
        fields = ["gender", "blood_type", "is_active"]

    def filter_name(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(pk__in=_patient_name_matches(queryset, value))

    def filter_has_whatsapp(self, queryset, name, value):
        if value:
            return queryset.exclude(whatsapp="")
        return queryset.filter(whatsapp="")


class PatientSearchFilter(BaseFilterBackend):
    """DRF ``?search=`` backend for Patient that handles encrypted name fields.

    Plaintext fields (medical_record_number, whatsapp) are matched in SQL.
    Encrypted fields are checked in one bounded-memory iterator pass and only
    matching ids return to the queryset, so raw identifiers are never exposed.
    """

    search_param = "search"

    def filter_queryset(self, request, queryset, view):
        term = request.query_params.get(self.search_param, "").strip()[:200]
        if not term:
            return queryset
        digits = _digits(term)
        plaintext_query = Q(medical_record_number__icontains=term) | Q(whatsapp__icontains=term)
        if len(digits) >= 4 and digits != term:
            plaintext_query |= Q(whatsapp__icontains=digits)
        sql_ids = set(queryset.filter(plaintext_query).values_list("id", flat=True))
        enc_ids = set(_patient_encrypted_matches(queryset, term))
        return queryset.filter(pk__in=sql_ids | enc_ids)

    def get_schema_operation_parameters(self, view):
        # Keep the `search` query param documented in the OpenAPI schema
        # (the built-in SearchFilter we replaced did this automatically).
        return [
            {
                "name": self.search_param,
                "required": False,
                "in": "query",
                "description": (
                    "Busca por nome, nome social, prontuário, CPF completo, CNS completo, "
                    "documento de identidade completo, telefone, WhatsApp ou e-mail. "
                    "Identificadores sensíveis aceitam somente correspondência exata."
                ),
                "schema": {"type": "string"},
            }
        ]
