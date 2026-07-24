"""Sprint E2 — serializers for the problem-oriented EMR surface.

``ProblemListItemSerializer`` and ``ImmunizationSerializer`` mirror the existing
EMR serializer conventions (display fields for choices, ``id``/timestamps read
only). ``ProblemListItem`` exposes the CID-10 through the ``cid10_code`` property
shim (write routes through the FK-resolving setter, exactly like
``MedicalHistorySerializer``).
"""

from rest_framework import serializers

from .models import Immunization, ProblemListItem
from .serializers import AllergySerializer


class AllergyRecordSerializer(AllergySerializer):
    """Standalone-viewset variant of AllergySerializer that carries ``patient``.

    The base ``AllergySerializer`` omits ``patient`` because the nested
    ``PatientViewSet.allergies`` action injects it via ``save(patient=...)``. The
    top-level ``/allergies/`` collection takes ``patient`` in the payload, so this
    subclass simply prepends it to the field list (required FK).
    """

    class Meta(AllergySerializer.Meta):
        fields = ["patient", *AllergySerializer.Meta.fields]


class ProblemListItemSerializer(serializers.ModelSerializer):
    clinical_status_display = serializers.CharField(
        source="get_clinical_status_display", read_only=True
    )
    verification_status_display = serializers.CharField(
        source="get_verification_status_display", read_only=True
    )
    # cid10 is a governed FK to core.CID10Code; the public write/read contract is
    # the plain code string, resolved through the property setter (matched → FK,
    # unmatched → legacy text + flag). Mirrors MedicalHistorySerializer.
    cid10_code = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = ProblemListItem
        fields = [
            "id",
            "patient",
            "encounter",
            "condition",
            "cid10_code",
            "cid_unmatched",
            "clinical_status",
            "clinical_status_display",
            "verification_status",
            "verification_status_display",
            "onset_date",
            "abatement_date",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "cid_unmatched", "created_at", "updated_at"]


class ImmunizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Immunization
        fields = [
            "id",
            "patient",
            "immunobiological",
            "dose_number",
            "lot",
            "manufacturer",
            "date",
            "pni_calendar_reference",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
