from rest_framework import serializers

from .models import CostCenter, Facility, LegalEntity, OrganizationalUnit


class ValidatedModelSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        instance = self.instance or self.Meta.model()
        for field, value in attrs.items():
            setattr(instance, field, value)
        instance.full_clean(exclude=None, validate_unique=False)
        return attrs


class LegalEntitySerializer(ValidatedModelSerializer):
    class Meta:
        model = LegalEntity
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")


class FacilitySerializer(ValidatedModelSerializer):
    class Meta:
        model = Facility
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")


class OrganizationalUnitSerializer(ValidatedModelSerializer):
    class Meta:
        model = OrganizationalUnit
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")


class CostCenterSerializer(ValidatedModelSerializer):
    class Meta:
        model = CostCenter
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")
