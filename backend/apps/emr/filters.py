import django_filters
from django.db.models import Q
from rest_framework.filters import BaseFilterBackend

from .models import Patient


def _patient_name_matches(queryset, term):
    """Return the ids of patients whose (decrypted) name fields contain ``term``.

    full_name / social_name are encrypted at rest, so they cannot be matched with
    SQL ``LIKE``. We decrypt in Python instead. This is O(n) over the active
    patient set — acceptable at clinic scale; revisit (e.g. a blind-index column)
    if the patient table grows large.
    """
    needle = term.lower()
    return [
        p.id
        for p in queryset.only("id", "full_name", "social_name")
        if needle in (p.full_name or "").lower() or needle in (p.social_name or "").lower()
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

    Plaintext fields (medical_record_number, whatsapp) are matched in SQL;
    encrypted fields (full_name, social_name) are decrypted and matched in
    Python. The two id sets are unioned so a single ``search`` term keeps
    working across all four fields.
    """

    search_param = "search"

    def filter_queryset(self, request, queryset, view):
        term = request.query_params.get(self.search_param, "").strip()
        if not term:
            return queryset
        sql_ids = set(
            queryset.filter(
                Q(medical_record_number__icontains=term) | Q(whatsapp__icontains=term)
            ).values_list("id", flat=True)
        )
        enc_ids = set(_patient_name_matches(queryset, term))
        return queryset.filter(pk__in=sql_ids | enc_ids)

    def get_schema_operation_parameters(self, view):
        # Keep the `search` query param documented in the OpenAPI schema
        # (the built-in SearchFilter we replaced did this automatically).
        return [
            {
                "name": self.search_param,
                "required": False,
                "in": "query",
                "description": "Busca por nome, nome social, prontuário ou WhatsApp.",
                "schema": {"type": "string"},
            }
        ]
