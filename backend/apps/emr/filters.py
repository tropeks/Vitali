import django_filters

from .models import Patient


class PatientFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name="full_name", lookup_expr="icontains")
    mrn = django_filters.CharFilter(field_name="medical_record_number", lookup_expr="icontains")
    gender = django_filters.ChoiceFilter(choices=Patient.GENDER_CHOICES)
    birth_date_from = django_filters.DateFilter(field_name="birth_date", lookup_expr="gte")
    birth_date_to = django_filters.DateFilter(field_name="birth_date", lookup_expr="lte")
    has_whatsapp = django_filters.BooleanFilter(method="filter_has_whatsapp")

    class Meta:
        model = Patient
        fields = ["gender", "blood_type", "is_active"]

    def filter_has_whatsapp(self, queryset, name, value):
        if value:
            return queryset.exclude(whatsapp="")
        return queryset.filter(whatsapp="")
