"""
Phase 2 ICP-Brasil digital signature primitive — tenant-scoped record of a
signed document. The signature payload is stored as raw bytes; the certificate
metadata is materialised so the record stays meaningful even if the original
cert is no longer available (rotated, revoked, expired).

CFM Res. 2.299/2021 + MP 2.200-2/2001 (ICP-Brasil) require:
- The signature is bound to the document hash, not just the document handle.
- The signer's identity is recorded with the cert subject and serial.
- The record is append-only (we use AuditLog elsewhere for the cascade trail).

This module exposes the storage layer only. The cryptographic primitive lives
in `apps.signatures.services.icp_brasil.ICPBrasilSigner`.
"""

import uuid

from django.db import models

from apps.core.models import User


class DigitalSignature(models.Model):
    """
    A signed document record. `document_type` + `document_id` form a polymorphic
    reference to whatever was signed — encounters, prescriptions, custom
    payloads. The store is intentionally append-only; revocation is tracked by
    creating a *new* row that supersedes the previous one (signatures are
    cryptographic facts, not editable state).
    """

    DOCUMENT_TYPE_ENCOUNTER = "encounter"
    DOCUMENT_TYPE_PRESCRIPTION = "prescription"
    DOCUMENT_TYPE_CUSTOM = "custom"

    DOCUMENT_TYPE_CHOICES = [
        (DOCUMENT_TYPE_ENCOUNTER, "Encounter"),
        (DOCUMENT_TYPE_PRESCRIPTION, "Prescription"),
        (DOCUMENT_TYPE_CUSTOM, "Custom"),
    ]

    ALGORITHM_SHA256_RSA = "SHA256withRSA"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_type = models.CharField(max_length=32, choices=DOCUMENT_TYPE_CHOICES)
    document_id = models.CharField(max_length=64)
    signer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="digital_signatures")

    # Cryptographic payload — bound to the document hash.
    signature = models.BinaryField()
    signature_algorithm = models.CharField(max_length=64, default=ALGORITHM_SHA256_RSA)
    document_hash_hex = models.CharField(max_length=128)

    # Certificate metadata at the time of signing.
    cert_subject = models.CharField(max_length=500)
    cert_issuer = models.CharField(max_length=500, blank=True, default="")
    cert_serial_hex = models.CharField(max_length=64)
    cert_not_valid_before = models.DateTimeField(null=True, blank=True)
    cert_not_valid_after = models.DateTimeField()
    is_icp_brasil = models.BooleanField(default=False)

    signed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-signed_at"]
        indexes = [
            models.Index(fields=["document_type", "document_id"], name="sig_doc_idx"),
            models.Index(fields=["signer", "-signed_at"], name="sig_signer_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.get_document_type_display()} {self.document_id} signed by "
            f"{self.signer_id} @ {self.signed_at:%Y-%m-%d %H:%M}"
        )
