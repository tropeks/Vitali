"""
Serializers for the ICP-Brasil signature module.

`SignatureCreateSerializer` accepts the document + the PKCS#12 bundle as
base64-encoded strings — the API surface deliberately never accepts the raw
private-key blob (e.g. via multipart upload) so the cert payload never lands
in middlewares that might log it. The serializer validates and decodes both;
the view orchestrates signing + storage.
"""

from __future__ import annotations

import base64

from rest_framework import serializers

from .models import DigitalSignature


class SignatureCreateSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=DigitalSignature.DOCUMENT_TYPE_CHOICES)
    document_id = serializers.CharField(max_length=64)
    document_b64 = serializers.CharField(write_only=True)
    pkcs12_b64 = serializers.CharField(write_only=True)
    pkcs12_password = serializers.CharField(
        write_only=True, allow_blank=True, default="", trim_whitespace=False
    )

    def validate_document_b64(self, value: str) -> bytes:
        return _b64decode(value, "document_b64")

    def validate_pkcs12_b64(self, value: str) -> bytes:
        return _b64decode(value, "pkcs12_b64")


class DigitalSignatureSerializer(serializers.ModelSerializer):
    signer_name = serializers.CharField(source="signer.full_name", read_only=True)
    signature_b64 = serializers.SerializerMethodField()

    class Meta:
        model = DigitalSignature
        fields = [
            "id",
            "document_type",
            "document_id",
            "signer",
            "signer_name",
            "signature_b64",
            "signature_algorithm",
            "document_hash_hex",
            "cert_subject",
            "cert_issuer",
            "cert_serial_hex",
            "cert_not_valid_before",
            "cert_not_valid_after",
            "is_icp_brasil",
            "signed_at",
        ]
        read_only_fields = fields

    def get_signature_b64(self, obj: DigitalSignature) -> str:
        raw = bytes(obj.signature) if obj.signature else b""
        return base64.b64encode(raw).decode("ascii")


def _b64decode(value: str, field: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (base64.binascii.Error, ValueError) as exc:  # type: ignore[attr-defined]
        raise serializers.ValidationError({field: f"Invalid base64: {exc}"}) from exc
